"""FlowHarmonic dashboard and destination controls."""
import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, StrictInt, StrictStr, field_validator

from . import SCHEMA_VERSION, VERSION
from .config import data_directory, load_config
from .local_audio import local_inventory
from .security import Authentication, COOKIE_AGE, SignInError
from .snapcast import AudioError, Snapcast
from .state import identity, initialize, node_name, set_node_name, validate_name
from .diagnostics import report as diagnostics_report
from .discovery import Discovery
from .network import MAX_MESSAGE, Membership, NetworkError

STATIC = Path(__file__).parent / 'static'
BUILD_FILE = Path(__file__).resolve().parent.parent / 'BUILD'
BUILD = BUILD_FILE.read_text().strip() if BUILD_FILE.exists() else f'{VERSION}-development'


class RouteChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: str = Field(min_length=1, max_length=1024)


class VolumeChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    percent: StrictInt | None = Field(default=None, ge=0, le=100)
    muted: StrictBool | None = None


class NameChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: StrictStr = Field(min_length=1, max_length=80)

    @field_validator('name')
    @classmethod
    def valid_name(cls, value):
        return validate_name(value)


class SignIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: SecretStr = Field(min_length=1, max_length=128)


class JoinRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: StrictStr = Field(min_length=1, max_length=512)
    identity: StrictStr | None = Field(default=None, max_length=36)


class JoinApproval(BaseModel):
    model_config = ConfigDict(extra='forbid')
    approve: StrictBool


class AllowJoining(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: StrictBool


def create_app():
    @asynccontextmanager
    async def lifespan(app):
        app.state.config = load_config()
        app.state.database = initialize(data_directory())
        app.state.authentication = Authentication(data_directory())
        app.state.cookie_name = 'fh_session_' + identity(app.state.database).replace('-', '')[:12]
        app.state.audio = Snapcast(app.state.config['snapcast_url'])
        app.state.membership = Membership(data_directory(), app.state.config, app.state.database)
        app.state.discovery = Discovery(app.state.membership, app.state.config)
        app.state.discovery.start()
        try:
            yield
        finally:
            await asyncio.to_thread(app.state.discovery.close)

    app = FastAPI(title='FlowHarmonic', version=VERSION, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(AudioError)
    async def audio_error(request, error):
        return JSONResponse(status_code=error.status, content={'detail': str(error)})

    @app.exception_handler(SignInError)
    async def sign_in_error(request, error):
        headers = {'Retry-After': '60'} if error.status == 429 else None
        return JSONResponse(status_code=error.status, content={'detail': str(error)}, headers=headers)

    @app.exception_handler(NetworkError)
    async def network_error(request, error):
        return JSONResponse(status_code=error.status, content={'detail': str(error)})

    def check_write_request(request: Request):
        # A custom header forces cross-origin browser requests through a CORS
        # preflight (which we do not allow). SameSite cookies add defense in depth.
        if request.headers.get('x-flowharmonic-request') != '1':
            raise HTTPException(403, 'Open this device’s dashboard directly to change audio settings.')
        origin = request.headers.get('origin')
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme != request.url.scheme or parsed.netloc != request.headers.get('host'):
                raise HTTPException(403, 'Open this device’s dashboard directly to change audio settings.')

    def session_token(request):
        return request.cookies.get(app.state.cookie_name, '')

    def require_sign_in(request: Request):
        if not app.state.authentication.authenticated(session_token(request)):
            raise HTTPException(401, 'Sign in to use FlowHarmonic.')

    def authorize(request: Request):
        require_sign_in(request)
        check_write_request(request)

    def signed_in_response(request, token):
        # Replace an earlier session in this browser rather than leaving it valid.
        app.state.authentication.sign_out(session_token(request))
        response = JSONResponse({'configured': True, 'authenticated': True})
        response.set_cookie(app.state.cookie_name, token, max_age=COOKIE_AGE,
                            httponly=True, samesite='strict', secure=request.url.scheme == 'https', path='/')
        response.delete_cookie(app.state.cookie_name, path='/api')
        return response

    @app.get('/health')
    def health():
        try:
            node_id = identity(app.state.database)
        except (sqlite3.Error, TypeError):
            return JSONResponse(status_code=503, content={'status': 'unavailable', 'version': VERSION})
        return {'status': 'ok', 'version': VERSION, 'identity': node_id,
                'schema_version': SCHEMA_VERSION, 'build': BUILD}

    @app.get('/api/node', dependencies=[Depends(require_sign_in)])
    def node():
        return {'identity': identity(app.state.database), 'name': node_name(app.state.database, app.state.config['name']), 'version': VERSION}

    @app.get('/api/settings', dependencies=[Depends(require_sign_in)])
    def settings():
        return {'name': node_name(app.state.database, app.state.config['name'])}

    @app.post('/api/settings', dependencies=[Depends(authorize)])
    def update_settings(change: NameChange):
        set_node_name(app.state.database, change.name)
        return settings()

    @app.get('/api/diagnostics', dependencies=[Depends(require_sign_in)])
    def diagnostics():
        result = diagnostics_report(app.state.config, app.state.database, app.state.audio, BUILD)
        result['checks'].append({'name': 'Node discovery', 'state': 'info', 'detail': app.state.discovery.snapshot()['message']})
        return result

    @app.get('/api/network', dependencies=[Depends(require_sign_in)])
    def network():
        return {**app.state.membership.view(), 'discovery': app.state.discovery.snapshot()}

    @app.post('/api/network/create', dependencies=[Depends(authorize)])
    def create_system(change: NameChange):
        return app.state.membership.create(change.name)

    @app.post('/api/network/allow', dependencies=[Depends(authorize)])
    def allow_joining(change: AllowJoining):
        return app.state.membership.allow(change.enabled)

    @app.post('/api/network/join', dependencies=[Depends(authorize)])
    def join_system(change: JoinRequest):
        return app.state.membership.request_join(change.url, change.identity)

    @app.post('/api/network/requests/{request_id}', dependencies=[Depends(authorize)])
    def approve_join(request_id: str, change: JoinApproval):
        return app.state.membership.approve(request_id, change.approve)

    @app.post('/api/network/sync', dependencies=[Depends(authorize)])
    def sync_system():
        return app.state.membership.sync()

    @app.post('/api/network/confirm', dependencies=[Depends(authorize)])
    def confirm_join():
        return app.state.membership.sync(confirm=True)

    @app.post('/api/network/cancel', dependencies=[Depends(authorize)])
    def cancel_join():
        return app.state.membership.cancel()

    @app.post('/api/network/leave', dependencies=[Depends(authorize)])
    def leave_system():
        return app.state.membership.leave()

    @app.post('/api/network/remove/{peer_id}', dependencies=[Depends(authorize)])
    def remove_member(peer_id: str):
        return app.state.membership.remove(peer_id)

    @app.get('/peer/info')
    def peer_info():
        # Minimal public enrollment metadata, never audio inventory or credentials.
        return app.state.membership.info()

    @app.post('/peer/message')
    async def peer_message(request: Request):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_MESSAGE:
                raise HTTPException(413, 'This node message is too large.')
        try:
            message = json.loads(raw)
        except ValueError:
            raise HTTPException(422, 'This node message is unreadable.')
        return await asyncio.to_thread(app.state.membership.receive, message)

    def local_view(inventory):
        return local_inventory(inventory, identity(app.state.database), app.state.config['snapcast_url'])

    def audio_snapshot():
        return local_view(app.state.audio.snapshot())

    @app.get('/api/audio', dependencies=[Depends(require_sign_in)])
    def audio():
        return audio_snapshot()

    @app.get('/api/sources', dependencies=[Depends(require_sign_in)])
    def sources():
        return {'sources': audio_snapshot()['sources']}

    @app.get('/api/destinations', dependencies=[Depends(require_sign_in)])
    def destinations():
        return {'destinations': audio_snapshot()['destinations']}

    @app.get('/api/auth')
    def authentication_status(request: Request):
        token = session_token(request)
        authenticated = app.state.authentication.authenticated(token)
        response = JSONResponse({'configured': app.state.authentication.configured(), 'authenticated': authenticated})
        if authenticated:
            # Upgrade remembered /api-only cookies so the normal page request
            # can authenticate too. Existing browsers do not need to sign in again.
            response.set_cookie(app.state.cookie_name, token, max_age=COOKIE_AGE,
                                httponly=True, samesite='strict', secure=request.url.scheme == 'https', path='/')
            response.delete_cookie(app.state.cookie_name, path='/api')
        return response

    @app.post('/api/auth/sign-in', dependencies=[Depends(check_write_request)])
    def sign_in(request: Request, credentials: SignIn):
        return signed_in_response(request, app.state.authentication.sign_in(credentials.password.get_secret_value()))

    @app.post('/api/auth/sign-out', dependencies=[Depends(check_write_request)])
    def sign_out(request: Request):
        app.state.authentication.sign_out(session_token(request))
        response = JSONResponse({'configured': app.state.authentication.configured(), 'authenticated': False})
        response.delete_cookie(app.state.cookie_name, path='/', httponly=True,
                               samesite='strict', secure=request.url.scheme == 'https')
        response.delete_cookie(app.state.cookie_name, path='/api')
        return response

    @app.post('/api/destinations/{destination:path}/source', dependencies=[Depends(authorize)])
    def route(destination: str, change: RouteChange):
        if change.source_id == 'Desktop Audio':
            source = next((s for s in audio_snapshot()['sources'] if s['id'] == change.source_id), None)
            if source and source['status'] == 'disabled':
                raise HTTPException(409, source.get('message', 'Desktop audio is unavailable.'))
        return local_view(app.state.audio.change(destination, source_id=change.source_id))

    @app.post('/api/destinations/{destination:path}/volume', dependencies=[Depends(authorize)])
    def volume(destination: str, change: VolumeChange):
        if change.percent is None and change.muted is None:
            raise HTTPException(422, 'Choose a volume or mute setting.')
        return local_view(app.state.audio.change(destination, percent=change.percent, muted=change.muted))

    @app.post('/api/destinations/{destination:path}/name', dependencies=[Depends(authorize)])
    def rename(destination: str, change: NameChange):
        return local_view(app.state.audio.rename(destination, change.name))

    @app.get('/')
    def dashboard(request: Request):
        if not app.state.authentication.authenticated(session_token(request)):
            return RedirectResponse('/sign-in', status_code=303)
        return FileResponse(STATIC / 'index.html')

    @app.get('/sign-in')
    def sign_in_page(request: Request):
        if app.state.authentication.authenticated(session_token(request)):
            return RedirectResponse('/', status_code=303)
        return FileResponse(STATIC / 'sign-in.html')

    app.mount('/static', StaticFiles(directory=STATIC), name='static')
    return app


app = create_app()
