# python -m uvicorn very_first:app --reload
import os
import time
import uuid  # НОВОЕ: генерация уникальных имён файлов
import hashlib
import pandas as pd
from PIL import Image
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi import FastAPI, Form, Request, HTTPException, status, Depends, File, UploadFile

SESSION_LIFE = 3600
USERS_FILE = "krivousers.csv"
ALLOVED_PICTURE = {".png", ".jpeg", ".webp", ".jpg"}

# НОВОЕ: папка для аватарок + лимит размера
AVATAR_DIR = os.path.join("static", "avatars")
MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2 МБ
os.makedirs(AVATAR_DIR, exist_ok=True)  # папка создастся сама, если её нет

def hash_password(password: str, salt: str = "") -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

def salt_for(username: str) -> str:
    # хэш имени как соль: у юзеров с одинаковым паролем хэши будут разные
    return hashlib.sha256(username.encode("utf-8")).hexdigest()

def _admin_row() -> pd.DataFrame:
    return pd.DataFrame([{
        "username": "admin",
        "password_hash": hash_password("1111", salt_for("admin")),
        "avatar": "",  # НОВОЕ
    }])

def get_users() -> pd.DataFrame:
    # файла нет / пустой / старый формат — чиним сами
    if not os.path.exists(USERS_FILE) or os.path.getsize(USERS_FILE) == 0:
        _admin_row().to_csv(USERS_FILE, index=False, encoding="utf-8")
    try:
        df = pd.read_csv(USERS_FILE)
    except pd.errors.ParserError:
        _admin_row().to_csv(USERS_FILE, index=False, encoding="utf-8")
        return pd.read_csv(USERS_FILE)
    if "password_hash" not in df.columns:  # старый CSV с колонкой password
        _admin_row().to_csv(USERS_FILE, index=False, encoding="utf-8")
        df = pd.read_csv(USERS_FILE)
    if "avatar" not in df.columns:  # НОВОЕ: чтобы старый CSV не сломал /home
        df["avatar"] = ""
    return df

def add_user(username: str, password: str, avatar: str = "") -> None:  # НОВОЕ: avatar
    row = pd.DataFrame([{
        "username": username,
        "password_hash": hash_password(password, salt_for(username)),
        "avatar": avatar,  # НОВОЕ
    }])
    header = not os.path.exists(USERS_FILE)
    row.to_csv(USERS_FILE, mode="a", index=False, header=header, encoding="utf-8")

# НОВОЕ: сохранение аватарки (бывшая логика вашей функции upload)
def save_avatar(file: UploadFile) -> str:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOVED_PICTURE:
        raise ValueError("Разрешены только .png, .jpg, .jpeg, .webp")
    if file.size and file.size > MAX_AVATAR_SIZE:
        raise ValueError("Файл больше 2 МБ")
    try:
        im = Image.open(file.file)
        im.verify()           # проверяем, что это правда изображение
        file.file.seek(0)     # verify «съедает» файл — перематываем
        im = Image.open(file.file)
    except Exception:
        raise ValueError("Это не картинка")
    if im.mode in ("RGBA", "LA", "P"):  # прозрачность -> белый фон, а не чёрный
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    fname = uuid.uuid4().hex + ".jpg"  # имя генерируем сами, файл каждого юзера отдельный
    im.save(os.path.join(AVATAR_DIR, fname), "JPEG", quality=85)
    im.close()
    return fname

app = FastAPI()
# ВНИМАНИЕ (не менял): https_only=True не даёт куке сохраниться по http —
# при локальном запуске uvicorn логин может «не работать» в Safari/curl
app.add_middleware(SessionMiddleware, secret_key="super-krivo-secret-key", max_age=SESSION_LIFE, https_only=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def current_user(request: Request) -> str:
    username = request.session.get("username")
    last_seen = request.session.get("last_seen")
    now = time.time()

    if not username or (last_seen and now - last_seen > SESSION_LIFE):
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ запрещен. Вы не авторизованы.",
        )
    request.session["last_seen"] = now
    return username

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 403:
        try:
            return templates.TemplateResponse(request=request, name="403.html", status_code=403)
        except Exception:
            return templates.TemplateResponse(request=request, name="404.html", status_code=403)
    return HTMLResponse(content=exc.detail, status_code=exc.status_code)

@app.get("/", response_class=HTMLResponse)
def main_page(request: Request):
    return templates.TemplateResponse(request=request, name="based_main.html")

@app.get("/home", response_class=HTMLResponse)
def home_page(request: Request, username: str = Depends(current_user)):
    df = get_users()
    row = df.loc[df["username"] == username]
    password_hash = str(row.iloc[0]["password_hash"]) if not row.empty else ""
    # НОВОЕ: ссылка на аватарку для шаблона
    avatar_name = str(row.iloc[0].get("avatar", "") or "") if not row.empty else ""
    avatar_url = f"/static/avatars/{avatar_name}" if avatar_name else ""
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"username": username, "password_hash": password_hash,
                 "avatar_url": avatar_url},  # НОВОЕ: avatar_url
    )

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request=request, name="register.html")


@app.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    avatar: UploadFile | None = File(None),  
):
    df = get_users()
    username = username.strip()  # НОВОЕ: пробелы не должны попадать в CSV
    if username in df["username"].astype(str).values:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "Такой пользователь уже существует"},
        )
    avatar_name = ""  # НОВОЕ
    if avatar is not None and avatar.filename:  # НОВОЕ: файл был выбран
        try:
            avatar_name = save_avatar(avatar)
        except ValueError as e:  # НОВОЕ: неверный файл -> показать ошибку на странице
            return templates.TemplateResponse(
                request=request,
                name="register.html",
                context={"error": str(e)},
            )
    add_user(username, password, avatar_name)  # НОВОЕ: третий аргумент
    request.session["username"] = username
    request.session["last_seen"] = time.time()

    return RedirectResponse("/home", status_code=302)

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    df = get_users()
    row = df.loc[df["username"] == username]
    if not row.empty:
        stored_hash = str(row.iloc[0]["password_hash"])
        if hash_password(password, salt_for(username)) == stored_hash:
            request.session["username"] = username
            request.session["last_seen"] = time.time()
            return RedirectResponse("/home", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "Неверный пароль или логин"},
    )

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)

@app.get("/404", response_class=HTMLResponse)
def _404_page(request: Request):
    return templates.TemplateResponse(request=request, name="404.html")