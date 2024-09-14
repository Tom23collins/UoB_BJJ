from fastapi import FastAPI, Request, Depends, HTTPException, status, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from fastapi_login import LoginManager
from datetime import datetime
from functools import wraps
import os
from werkzeug.security import generate_password_hash, check_password_hash
from db import db_query, db_update, db_query_values
import config
from scripts import format_date, send_welcome_email

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Initialize LoginManager
SECRET = config.SECRET_KEY
manager = LoginManager(SECRET, token_url='/login', use_cookie=True)
manager.cookie_name = 'auth_token'

# Mail configurations
app.state.MAIL_SERVER = config.MAIL_SERVER
app.state.MAIL_PORT = config.MAIL_PORT
app.state.MAIL_USE_SSL = config.MAIL_USE_SSL
app.state.MAIL_USERNAME = config.MAIL_USERNAME
app.state.MAIL_PASSWORD = config.MAIL_KEY

# If in development, set debug mode
if os.getenv('FLASK_ENV') == 'development':
    app.debug = True

# User model
class User:
    def __init__(self, id, password, first_name, last_name, medical_info, user_role):
        self.id = id
        self.password = password
        self.first_name = first_name
        self.last_name = last_name
        self.medical_info = medical_info
        self.user_role = user_role

@manager.user_loader()
def load_user(email: str):
    user_data = db_query_values('SELECT * FROM user_table WHERE email = %s', (email,))
    if not user_data:
        return None
    user = User(
        id=user_data[0][0],
        password=user_data[0][1],
        first_name=user_data[0][2],
        last_name=user_data[0][3],
        medical_info=user_data[0][4],
        user_role=user_data[0][5]
    )
    return user

def role_required(role: str):
    async def role_checker(user: User = Depends(manager)):
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='You need to be logged in to access this page.')
        if user.user_role == 'administrator':
            return user
        if user.user_role != role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have the required role to access this page.")
        return user
    return Depends(role_checker)

@app.get('/', response_class=HTMLResponse)
async def index(request: Request):
    user = None
    try:
        user = manager.get_current_user()
    except:
        pass

    current_date = datetime.now().strftime('%Y-%m-%d')
    session_data = db_query_values('SELECT * FROM event_table WHERE date >= %s', (current_date,))
    
    updated_sessions = []
    registration_event_ids = set()
    user_registrations = {}

    if user:
        registrations = db_query_values('SELECT event_id, booked_gi FROM sign_up_log WHERE email = %s', (user.id,))
        registration_event_ids = {int(registration[0]) for registration in registrations}
        user_registrations = {int(registration[0]): registration[1] for registration in registrations}

    session_ids = tuple(session[0] for session in session_data)

    if session_ids:
        placeholders = ', '.join(['%s'] * len(session_ids))
        registration_counts = db_query_values(f'SELECT event_id, COUNT(*) FROM sign_up_log WHERE event_id IN ({placeholders}) GROUP BY event_id', session_ids)
        registration_count_dict = {int(row[0]): row[1] for row in registration_counts}
        gis_booked_counts = db_query_values(f'SELECT event_id, COUNT(*) FROM sign_up_log WHERE event_id IN ({placeholders}) AND booked_gi = 1 GROUP BY event_id', session_ids)
        gis_booked_dict = {int(row[0]): row[1] for row in gis_booked_counts}
    else:
        registration_count_dict = {}
        gis_booked_dict = {}

    for session in session_data:
        event_id = int(session[0])
        registered = event_id in registration_event_ids if user else False
        booked_gi = bool(user_registrations.get(event_id, False)) if registered else False

        event = {
            'event_id': event_id,
            'event_name': session[1],
            'date': format_date(session[2]),
            'start_time': datetime.strptime(str(session[3]), "%H:%M:%S").strftime("%H:%M"),
            'end_time': datetime.strptime(str(session[4]), "%H:%M:%S").strftime("%H:%M"),
            'category': session[5],
            'capacity': session[6] - registration_count_dict.get(event_id, 0),
            'location': session[7],
            'location_link': session[8],
            'registered': registered,
            'registration_count': registration_count_dict.get(event_id, 0),
            'booked_gi': booked_gi,
            'gis_booked': gis_booked_dict.get(event_id, 0),
            'event_topic': session[9],
            'event_coach': session[10],
        }

        updated_sessions.append(event)

    return templates.TemplateResponse('index.html', {"request": request, "event_data": updated_sessions, "user": user})

@app.get('/about', response_class=HTMLResponse)
async def about(request: Request):
    user = None
    try:
        user = manager.get_current_user()
    except:
        pass
    return templates.TemplateResponse('about.html', {'request': request, 'user': user})

@app.get('/class-sign-up')
async def class_sign_up(event_id: int, user: User = Depends(manager)):
    sql = """
    INSERT INTO sign_up_log (`email`, `event_id`, `timestamp`) 
    VALUES (%s, %s, %s)
    """
    values = (user.id, event_id, datetime.now())
    db_update(sql, values)
    return RedirectResponse(url='/', status_code=status.HTTP_302_FOUND)

@app.get('/cancel-sign-up')
async def cancel_sign_up(event_id: int, user: User = Depends(manager)):
    sql = """
        DELETE FROM sign_up_log
        WHERE email = %s 
        AND event_id = %s
    """
    values = (user.id, event_id)
    db_update(sql, values)
    return RedirectResponse(url='/', status_code=status.HTTP_302_FOUND)

@app.get('/register', response_class=HTMLResponse)
async def register_get(request: Request):
    return templates.TemplateResponse('user_register.html', {'request': request})

@app.post('/register')
async def register_post(email: str = Form(...), password: str = Form(...), first_name: str = Form(...), last_name: str = Form(...), medical_info: str = Form(...)):
    sql = """
    INSERT INTO user_table (`email`, `password`, `first_name`, `last_name`, `medical_info`)
    VALUES (%s, %s, %s, %s, %s)
    """
    values = (
        email,
        generate_password_hash(password),
        first_name,
        last_name,
        medical_info
    )
    db_update(sql, values)

    send_welcome_email(email, first_name)

    return RedirectResponse(url='/login', status_code=status.HTTP_302_FOUND)

@app.get('/login', response_class=HTMLResponse)
async def login_get(request: Request):
    return templates.TemplateResponse('user_login.html', {'request': request})

@app.post('/login')
async def login_post(request: Request, email: str = Form(...), password: str = Form(...)):
    user = load_user(email)
    if user and check_password_hash(user.password, password):
        access_token = manager.create_access_token(
            data={'sub': email}
        )
        response = RedirectResponse(url='/', status_code=status.HTTP_302_FOUND)
        manager.set_cookie(response, access_token)
        return response

    error = "Invalid email or password. Please contact a committee member if you have forgotten your login."
    return templates.TemplateResponse('user_login.html', {'request': request, 'error': error})

@app.get('/book-taster-gi')
async def book_taster_gi(event_id: int, user: User = Depends(manager)):
    sql = """
    UPDATE sign_up_log
    SET booked_gi = 1
    WHERE email = %s AND event_id = %s;
    """
    values = (user.id, event_id)
    db_update(sql, values)
    return RedirectResponse(url='/', status_code=status.HTTP_302_FOUND)

@app.get('/logout')
def logout():
    response = RedirectResponse(url='/', status_code=status.HTTP_302_FOUND)
    response.delete_cookie(manager.cookie_name)
    return response

# Committee views
@app.get('/sign-ups', response_class=HTMLResponse)
async def view_sign_ups(request: Request, event_id: int, user: User = role_required('committee')):
    sign_up_data = []
    sql = "SELECT * FROM sign_up_log WHERE event_id = %s"
    for sign_ups in db_query_values(sql, (event_id,)):
        names = db_query_values("SELECT first_name, last_name FROM user_table WHERE email = %s", (sign_ups[1],))
        sign_up = {
            'first_name': names[0][0],
            'last_name': names[0][1],
            'booked_gi': bool(sign_ups[4])
        }
        sign_up_data.append(sign_up)
    data = db_query_values('SELECT * FROM event_table WHERE event_id = %s', (event_id,))
    event = {
        'event_id': data[0][0],
        'event_name': data[0][1],
        'date': format_date(data[0][2]),
        'start_time': datetime.strptime(str(data[0][3]), "%H:%M:%S").strftime("%H:%M"),
        'end_time': datetime.strptime(str(data[0][4]), "%H:%M:%S").strftime("%H:%M"),
        'category': data[0][5],
        'capacity': data[0][6],
        'location': data[0][7]
    }
    return templates.TemplateResponse('/committee/sign_ups.html', {'request': request, 'user': user, 'event_data': event, 'data': sign_up_data})

@app.get('/new-event', response_class=HTMLResponse)
async def create_new_event_get(request: Request, user: User = role_required('committee')):
    return templates.TemplateResponse('/committee/create_new_event.html', {'request': request, 'user': user})

@app.post('/new-event')
async def create_new_event_post(event_name: str = Form(...), date: str = Form(...), start_time: str = Form(...), end_time: str = Form(...), category: str = Form(...), capacity: int = Form(...), location: str = Form(...), location_link: str = Form(None), event_topic: str = Form(None), event_coach: str = Form(None), user: User = role_required('committee')):
    sql = """
    INSERT INTO event_table (`event_name`, `date`, `start_time`, `end_time`, `category`, `capacity`, `location`, `location_link`, `event_topic`, `event_coach`)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    values = (
        event_name,
        date,
        start_time,
        end_time,
        category,
        capacity,
        location,
        location_link,
        event_topic,
        event_coach
    )
    db_update(sql, values)
    return RedirectResponse(url='/new-event', status_code=status.HTTP_302_FOUND)

@app.get('/edit-event', response_class=HTMLResponse)
async def edit_event_get(request: Request, event_id: int, user: User = role_required('committee')):
    data = db_query_values('SELECT * FROM event_table WHERE event_id = %s', (event_id,))
    event = {
        'event_id': data[0][0],
        'event_name': data[0][1],
        'date': data[0][2].strftime("%Y-%m-%d"),
        'start_time': datetime.strptime(str(data[0][3]), "%H:%M:%S").strftime("%H:%M"),
        'end_time': datetime.strptime(str(data[0][4]), "%H:%M:%S").strftime("%H:%M"),
        'category': data[0][5],
        'capacity': data[0][6],
        'location': data[0][7],
        'location_link': data[0][8],
        'event_topic': data[0][9],
        'event_coach': data[0][10]
    }
    return templates.TemplateResponse('/committee/edit_event.html', {'request': request, 'user': user, 'data': event})

@app.post('/edit-event')
async def edit_event_post(event_id: int = Form(...), event_name: str = Form(...), date: str = Form(...), start_time: str = Form(...), end_time: str = Form(...), category: str = Form(...), capacity: int = Form(...), location: str = Form(...), location_link: str = Form(None), event_topic: str = Form(None), event_coach: str = Form(None), user: User = role_required('committee')):
    sql = """
    UPDATE event_table
    SET event_name = %s, date = %s, start_time = %s, end_time = %s, category = %s, 
        capacity = %s, location = %s, location_link = %s, event_topic=%s, event_coach=%s
    WHERE event_id = %s
    """
    values = (
        event_name,
        date,
        start_time,
        end_time,
        category,
        capacity,
        location,
        location_link,
        event_topic,
        event_coach,
        event_id,
    )
    db_update(sql, values)
    return RedirectResponse(url='/', status_code=status.HTTP_302_FOUND)

@app.get('/members', response_class=HTMLResponse)
async def members(request: Request, user: User = role_required('committee')):
    data = []
    for users in db_query('SELECT * FROM user_table'):
        user_data = {
            'email': users[0],
            'first_name': users[2],
            'last_name': users[3],
            'medical_info': users[4],
            'user_role': users[5]
        }
        data.append(user_data)
    return templates.TemplateResponse('/committee/members.html', {'request': request, 'user': user, 'data': data})

@app.get('/update-password')
async def update_password(email: str, password: str, user: User = role_required('committee')):
    sql = """
    UPDATE user_table
    SET `password` = %s
    WHERE `email` = %s
    """
    values = (
        generate_password_hash(password),
        email,
    )
    db_update(sql, values)
    return RedirectResponse(url='/members', status_code=status.HTTP_302_FOUND)

@app.get('/update-role')
async def update_role(email: str, user_role: str, user: User = role_required('committee')):
    sql = """
    UPDATE user_table
    SET `user_role` = %s
    WHERE `email` = %s
    """
    values = (
        user_role,
        email,
    )
    db_update(sql, values)
    return RedirectResponse(url='/members', status_code=status.HTTP_302_FOUND)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app)