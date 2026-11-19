import os
import time
import uuid  # генерация уникальных имён файлов
import shutil  # копирование видеофайла на диск
import hashlib
from datetime import datetime
import pandas as pd
from PIL import Image
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi import FastAPI, Form, Request, HTTPException, status, Depends, File, UploadFile

SESSION_LIFE = 3600
USERS_FILE = "krivousers.csv"
POSTS_FILE = "krivoposts.csv"        # публикации
COMMENTS_FILE = "krivocomments.csv"  # комментарии
ALLOVED_PICTURE = {".png", ".jpeg", ".webp", ".jpg"}
ALLOWED_VIDEO = {".mp4", ".webm", ".mov"}

# папки для картинок/видео (создаются сами)
AVATAR_DIR = os.path.join("static", "avatars")
POSTPICS_DIR = os.path.join("static", "postpics")
MAX_AVATAR_SIZE = 2 * 1024 * 1024   # 2 МБ
MAX_VIDEO_SIZE = 50 * 1024 * 1024   # 50 МБ
os.makedirs(AVATAR_DIR, exist_ok=True)
os.makedirs(POSTPICS_DIR, exist_ok=True)


# ==================== ПОЛЬЗОВАТЕЛИ ====================

def hash_password(password: str, salt: str = "") -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def salt_for(username: str) -> str:
    # хэш имени как соль: у юзеров с одинаковым паролем хэши разные
    return hashlib.sha256(username.encode("utf-8")).hexdigest()


def _admin_row() -> pd.DataFrame:
    return pd.DataFrame([{
        "username": "admin",
        "password_hash": hash_password("1111", salt_for("admin")),
        "avatar": "",
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
    if "avatar" not in df.columns:
        df["avatar"] = ""
    df["avatar"] = df["avatar"].fillna("").astype(str)  # пустые поля -> "" (не NaN!)
    return df


def add_user(username: str, password: str, avatar: str = "") -> None:
    row = pd.DataFrame([{
        "username": username,
        "password_hash": hash_password(password, salt_for(username)),
        "avatar": avatar,
    }])
    header = not os.path.exists(USERS_FILE)
    row.to_csv(USERS_FILE, mode="a", index=False, header=header, encoding="utf-8")


# ==================== КАРТИНКИ И ВИДЕО ====================

def save_avatar(file: UploadFile, directory: str = AVATAR_DIR) -> str:
    """Сохраняет картинку (аватарку или фото к посту)."""
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
    fname = uuid.uuid4().hex + ".jpg"  # имя генерируем сами
    im.save(os.path.join(directory, fname), "JPEG", quality=85)
    im.close()
    return fname


def save_video(file: UploadFile, directory: str = POSTPICS_DIR) -> str:
    """Сохраняет видео к посту (.mp4 / .webm / .mov, до 50 МБ)."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_VIDEO:
        raise ValueError("Видео: только .mp4, .webm или .mov")
    size = file.size
    if size is None:  # на случай старой версии Starlette
        file.file.seek(0, os.SEEK_END)
        size = file.file.tell()
        file.file.seek(0)
    if size > MAX_VIDEO_SIZE:
        raise ValueError("Видео больше 50 МБ")
    fname = uuid.uuid4().hex + ext  # имя генерирует сервер
    with open(os.path.join(directory, fname), "wb") as out:
        file.file.seek(0)
        shutil.copyfileobj(file.file, out)
    return fname


# ==================== ПОСТЫ ====================

def get_posts() -> pd.DataFrame:
    seed = pd.DataFrame([
        {"id": 1, "username": "admin",
         "text": "Добро пожаловать! Теперь можно публиковать записи с фото и видео и комментировать.",
         "created": "2025-01-01 12:00", "image": "", "video": ""},
        {"id": 2, "username": "admin",
         "text": "Правила простые: будьте вежливы, не спамьте. Приятного общения!",
         "created": "2025-01-01 12:05", "image": "", "video": ""},
    ])
    if not os.path.exists(POSTS_FILE) or os.path.getsize(POSTS_FILE) == 0:
        seed.to_csv(POSTS_FILE, index=False, encoding="utf-8")
    try:
        df = pd.read_csv(POSTS_FILE)
    except pd.errors.ParserError:
        seed.to_csv(POSTS_FILE, index=False, encoding="utf-8")
        df = pd.read_csv(POSTS_FILE)
    if "image" not in df.columns:  # миграции старых файлов
        df["image"] = ""
        df.to_csv(POSTS_FILE, index=False, encoding="utf-8")
    if "video" not in df.columns:
        df["video"] = ""
        df.to_csv(POSTS_FILE, index=False, encoding="utf-8")
    df["image"] = df["image"].fillna("").astype(str)
    df["video"] = df["video"].fillna("").astype(str)
    df["text"] = df["text"].fillna("").astype(str)
    df["username"] = df["username"].fillna("").astype(str)
    return df


def add_post(username: str, text: str, image: str = "", video: str = "") -> None:
    df = get_posts()
    new_id = int(df["id"].max()) + 1 if not df.empty else 1
    row = pd.DataFrame([{
        "id": new_id,
        "username": username,
        "text": text.strip()[:500],
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "image": image,
        "video": video,
    }])
    header = not os.path.exists(POSTS_FILE)
    row.to_csv(POSTS_FILE, mode="a", index=False, header=header, encoding="utf-8")


# ==================== КОММЕНТАРИИ ====================

def get_comments() -> pd.DataFrame:
    if not os.path.exists(COMMENTS_FILE) or os.path.getsize(COMMENTS_FILE) == 0:
        pd.DataFrame(columns=["id", "post_id", "username", "text", "created"]
                     ).to_csv(COMMENTS_FILE, index=False, encoding="utf-8")
    try:
        df = pd.read_csv(COMMENTS_FILE)
    except pd.errors.ParserError:
        pd.DataFrame(columns=["id", "post_id", "username", "text", "created"]
                     ).to_csv(COMMENTS_FILE, index=False, encoding="utf-8")
        df = pd.read_csv(COMMENTS_FILE)
    df["username"] = df["username"].fillna("").astype(str)
    df["text"] = df["text"].fillna("").astype(str)
    return df


def add_comment(post_id: int, username: str, text: str) -> None:
    df = get_comments()
    new_id = int(df["id"].max()) + 1 if not df.empty else 1
    row = pd.DataFrame([{
        "id": new_id,
        "post_id": post_id,
        "username": username,
        "text": text.strip()[:300],
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }])
    header = not os.path.exists(COMMENTS_FILE)
    row.to_csv(COMMENTS_FILE, mode="a", index=False, header=header, encoding="utf-8")


# ==================== ПРИЛОЖЕНИЕ ====================

app = FastAPI()
# ВНИМАНИЕ: https_only=True не даёт куке сохраниться по http.
# Если после логина видишь 403 (особенно по IP, а не localhost) —
# поставь https_only=False для локальной разработки.
app.add_middleware(SessionMiddleware, secret_key="super-krivo-secret-key",
                   max_age=SESSION_LIFE, https_only=True)
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
    # аватарки всех юзеров (для авторов постов и комментаторов)
    users = get_users()
    users["avatar"] = users["avatar"].fillna("").astype(str)
    avatars = {str(u["username"]): (f"/static/avatars/{u['avatar']}" if u["avatar"] else "")
               for _, u in users.iterrows()}

    # посты (свежие сверху) и комментарии, сгруппированные по post_id
    posts = get_posts().sort_values("id", ascending=False)
    comments = get_comments().sort_values("id")

    comments_by_post = {}
    for _, c in comments.iterrows():
        comments_by_post.setdefault(int(c["post_id"]), []).append({
            "author": str(c["username"]),
            "avatar_url": avatars.get(str(c["username"]), ""),
            "text": str(c["text"]),
            "created": str(c["created"]),
        })

    feed = [{
        "id": int(p["id"]),
        "author": str(p["username"]),
        "avatar_url": avatars.get(str(p["username"]), ""),
        "text": str(p["text"]),
        "created": str(p["created"]),
        "image_url": (f"/static/postpics/{p['image']}" if p["image"] else ""),
        "video_url": (f"/static/postpics/{p['video']}" if p["video"] else ""),
        "comments": comments_by_post.get(int(p["id"]), []),
    } for _, p in posts.iterrows()]

    return templates.TemplateResponse(
        request=request, name="home.html",
        context={
            "username": username,
            "avatar_url": avatars.get(username, ""),
            "posts": feed,
            "error": request.session.pop("error", None),  # ошибка загрузки файла (если была)
        },
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
    username = username.strip()
    if not username or not password:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "Логин и пароль не могут быть пустыми"},
        )
    if username in df["username"].astype(str).values:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "Такой пользователь уже существует", "username": username},
        )
    avatar_name = ""
    if avatar is not None and avatar.filename:
        try:
            avatar_name = save_avatar(avatar)
        except ValueError as e:
            return templates.TemplateResponse(
                request=request,
                name="register.html",
                context={"error": str(e), "username": username},
            )
    add_user(username, password, avatar_name)
    request.session["username"] = username
    request.session["last_seen"] = time.time()

    return RedirectResponse("/home", status_code=303)


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
            request.session.clear()  # защита от session fixation
            request.session["username"] = username
            request.session["last_seen"] = time.time()
            return RedirectResponse("/home", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "Неверный пароль или логин", "username": username},
    )


@app.post("/post")
def create_post(request: Request, text: str = Form(...),
                media: UploadFile | None = File(None),
                username: str = Depends(current_user)):
    media_image, media_video = "", ""
    if media is not None and media.filename:
        ext = os.path.splitext(media.filename or "")[1].lower()
        try:
            if ext in ALLOWED_VIDEO:
                media_video = save_video(media)                  # это видео
            elif ext in ALLOVED_PICTURE:
                media_image = save_avatar(media, POSTPICS_DIR)   # это фото
            else:
                raise ValueError("Можно приложить фото (.png/.jpg/.webp) или видео (.mp4/.webm/.mov)")
        except ValueError as e:
            request.session["error"] = str(e)
            return RedirectResponse("/home", status_code=303)
    if text.strip() or media_image or media_video:
        add_post(username, text, media_image, media_video)
    return RedirectResponse("/home", status_code=303)


@app.post("/comment")
def comment(request: Request, post_id: int = Form(...), text: str = Form(...),
            username: str = Depends(current_user)):
    if text.strip() and post_id in set(get_posts()["id"].astype(int)):
        add_comment(post_id, username, text)
    return RedirectResponse("/home", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/404", response_class=HTMLResponse)
def _404_page(request: Request):
    return templates.TemplateResponse(request=request, name="404.html")