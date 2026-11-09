#!/usr/bin/env python3
"""
FERI Praksa Notifier Bot
Avtor: Ziga Pesti
Namen: Avtomatsko 24/7 spremljanje strani https://feri.um.si/praksa/ in
       takojšnje obveščanje po e-pošti in na telefon ob vsaki novi objavi.
"""

import sys
import os
import time
import json
import sqlite3
import smtplib
import ssl
import re
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from html import unescape
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# Poti do datotek
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
DB_FILE = os.path.join(BASE_DIR, "praksa_state.db")
SEEN_JSON_FILE = os.path.join(BASE_DIR, "seen_posts.json")
LOG_FILE = os.path.join(BASE_DIR, "bot.log")

URL_PRAKSA = "https://feri.um.si/praksa/"
URL_PRAKSA_RSS = "https://feri.um.si/praksa/rss/"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


def log(msg: str):
    """Izpiše sporočilo v konzolo in ga zapiše v log datoteko."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] {msg}"
    print(formatted)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass


def load_config() -> dict:
    """Naloži konfiguracijsko datoteko config.json ali okoljske spremenljivke."""
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            log(f"Opozorilo pri branju config.json: {e}")

    # Okoljske spremenljivke imajo prednost (za GitHub Actions / Docker)
    email_cfg = cfg.setdefault("email", {})
    if os.environ.get("SMTP_PASSWORD"):
        email_cfg["smtp_password"] = os.environ["SMTP_PASSWORD"]
    if os.environ.get("SMTP_USER"):
        email_cfg["smtp_user"] = os.environ["SMTP_USER"]
    if os.environ.get("RECIPIENT_EMAIL"):
        email_cfg["recipient_email"] = os.environ["RECIPIENT_EMAIL"]
    if os.environ.get("SMTP_SERVER"):
        email_cfg["smtp_server"] = os.environ["SMTP_SERVER"]

    ntfy_cfg = cfg.setdefault("ntfy_phone_notification", {})
    if os.environ.get("NTFY_TOPIC"):
        ntfy_cfg["topic"] = os.environ["NTFY_TOPIC"]

    return cfg


def init_db():
    """Inicializira lokalno SQLite bazo podatkov za shranjevanje videnih objav."""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS seen_posts (
                post_id TEXT PRIMARY KEY,
                title TEXT,
                url TEXT,
                first_seen_at TEXT
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"Opozorilo pri inicializaciji SQLite baze: {e}")


def load_seen_posts() -> set[str]:
    """Naloži seznam že videnih ID-jev iz seen_posts.json ali SQLite."""
    seen = set()
    if os.path.exists(SEEN_JSON_FILE):
        try:
            with open(SEEN_JSON_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                seen.update(data.keys())
        except Exception:
            pass

    if os.path.exists(DB_FILE):
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT post_id FROM seen_posts")
            for row in c.fetchall():
                seen.add(str(row[0]))
            conn.close()
        except Exception:
            pass
    return seen


def mark_post_seen(post_id: str, title: str, url: str):
    """Zabeleži objavo v seen_posts.json in SQLite."""
    now_str = datetime.now().isoformat()
    # 1. Shrani v seen_posts.json (zaradi git diffa v GitHub Actions)
    data = {}
    if os.path.exists(SEEN_JSON_FILE):
        try:
            with open(SEEN_JSON_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data[str(post_id)] = {
        "title": title,
        "url": url,
        "seen_at": now_str
    }
    with open(SEEN_JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # 2. Shrani v SQLite če baza obstaja ali se ustvari
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS seen_posts (
                post_id TEXT PRIMARY KEY,
                title TEXT,
                url TEXT,
                first_seen_at TEXT
            )
        """)
        c.execute("""
            INSERT OR REPLACE INTO seen_posts (post_id, title, url, first_seen_at)
            VALUES (?, ?, ?, ?)
        """, (str(post_id), title, url, now_str))
        conn.commit()
        conn.close()
    except Exception:
        pass


def is_post_seen(post_id: str) -> bool:
    """Preveri, ali je bil post že viden."""
    seen = load_seen_posts()
    return str(post_id) in seen


def fetch_url(url: str, timeout: int = 15) -> str:
    """Naloži vsebino spletne strani z določenim uporabniškim agentom."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "sl,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def parse_html_notices(html: str) -> tuple[bool, list[dict]]:
    """
    Analizira HTML strani https://feri.um.si/praksa/
    Vrne: (has_no_notices, notices_list)
    """
    # 1. Preveri prisotnost niza "Ni obvestil"
    has_no_notices = "Ni obvestil" in html

    # 2. Poišči vse <article> z objavami
    notices = []
    pattern = re.compile(r"<article[^>]*id=['\"]post-(\d+)['\"][^>]*>(.*?)</article>", re.DOTALL)
    matches = pattern.findall(html)

    for pid, body in matches:
        # Če ima oznako 'novica-potekla', je potekla
        if "novica-potekla" in body:
            continue

        tm = re.search(r"<h3[^>]*><a[^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", body)
        raw_title = tm.group(2) if tm else "Nova objava za prakso"
        title = unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
        link = tm.group(1) if tm else ""
        if link and not link.startswith("http"):
            link = "https://feri.um.si" + link

        date_m = re.search(r"<p class=['\"]novica-datum['\"]>(.*?)</p>", body)
        date_str = unescape(re.sub(r"<[^>]+>", "", date_m.group(1))).strip() if date_m else ""

        desc_m = re.search(r"<div class=['\"]novica-vsebina['\"]>(.*?)</div>", body, re.DOTALL)
        desc = ""
        if desc_m:
            desc = unescape(re.sub(r"<[^>]+>", " ", desc_m.group(1)))
            desc = " ".join(desc.split())[:350] + "..."

        notices.append({
            "id": pid,
            "title": title,
            "url": link or URL_PRAKSA,
            "date": date_str,
            "description": desc,
        })

    return has_no_notices, notices


def parse_rss_notices() -> list[dict]:
    """Preveri še uradni RSS vir kot dodatno varnost."""
    notices = []
    try:
        xml_content = fetch_url(URL_PRAKSA_RSS, timeout=10)
        root = ET.fromstring(xml_content)
        channel = root.find("channel")
        if channel is not None:
            for item in channel.findall("item"):
                title = item.findtext("title", default="Objava za prakso").strip()
                link = item.findtext("link", default=URL_PRAKSA).strip()
                desc = item.findtext("description", default="").strip()
                pub_date = item.findtext("pubDate", default="").strip()
                # Ustvari ID iz povezave ali naslova
                pid = re.sub(r"[^a-zA-Z0-9]", "", link) or str(hash(title))
                notices.append({
                    "id": pid,
                    "title": title,
                    "url": link,
                    "date": pub_date,
                    "description": desc[:300],
                })
    except Exception as e:
        log(f"Opozorilo pri branju RSS: {e}")
    return notices


def send_email_alert(config: dict, notice: dict):
    """Pošlje e-poštno obvestilo preko SMTP (Gmail ali poljuben SMTP)."""
    email_cfg = config.get("email", {})
    if not email_cfg.get("enabled", False):
        log("E-poštna obvestila so izklopljena v config.json.")
        return

    smtp_user = email_cfg.get("smtp_user", "")
    smtp_pass = email_cfg.get("smtp_password", "")
    recipient = email_cfg.get("recipient_email", smtp_user)
    smtp_server = email_cfg.get("smtp_server", "smtp.gmail.com")
    smtp_port = email_cfg.get("smtp_port", 587)

    if "VNESI" in smtp_pass or "TUKAJ" in smtp_pass or not smtp_pass:
        log("OPOZORILO: V config.json se nisi vpisal svojega Gmail gesla za aplikacije (smtp_password)!")
        return

    subject = f"🚨 NOVA PRAKSA NA FERI: {notice['title']}"

    # HTML telo
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f4f6f8; padding: 20px; color: #1e293b;">
      <div style="max-width: 600px; margin: auto; background: #ffffff; border-radius: 8px; padding: 25px; border-left: 6px solid #2563eb; box-shadow: 0 4px 15px rgba(0,0,0,0.08);">
        <h2 style="color: #1e3a8a; margin-top: 0;">🎓 Nova objava za praktično usposabljanje na FERI!</h2>
        <p style="font-size: 16px; margin: 15px 0;">Na spletni strani <strong>feri.um.si/praksa/</strong> je bila pravkar zaznana nova objava:</p>
        
        <div style="background: #f1f5f9; padding: 15px; border-radius: 6px; margin: 20px 0;">
          <h3 style="margin: 0 0 8px 0; color: #0f172a; font-size: 18px;">{notice['title']}</h3>
          {f"<p style='color: #64748b; font-size: 13px; margin: 0 0 10px 0;'>📅 {notice['date']}</p>" if notice.get('date') else ""}
          {f"<p style='font-size: 14px; line-height: 1.5; color: #334155;'>{notice['description']}</p>" if notice.get('description') else ""}
        </div>

        <p style="text-align: center; margin: 30px 0 15px 0;">
          <a href="{notice['url']}" style="background-color: #2563eb; color: #ffffff; padding: 12px 26px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 15px; display: inline-block;">
            Odpri objavo na FERI &rarr;
          </a>
        </p>

        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 25px 0 15px 0;" />
        <p style="font-size: 12px; color: #94a3b8; text-align: center; margin: 0;">
          Avtomatsko obvestilo bota FERI Praksa Notifier &bull; Zaznano: {datetime.now().strftime('%d.%m.%Y ob %H:%M:%S')}
        </p>
      </div>
    </body>
    </html>
    """

    # Navadno besedilo kot rezerva
    plain_text = f"""
    NOVA OBJAVA ZA PRAKSO NA FERI!
    
    Naslov: {notice['title']}
    Datum: {notice.get('date', 'N/A')}
    Povezava: {notice['url']}
    
    Opis:
    {notice.get('description', '')}
    
    --
    FERI Praksa Notifier Bot ({datetime.now().strftime('%d.%m.%Y %H:%M:%S')})
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"FERI Praksa Bot <{smtp_user}>"
    msg["To"] = recipient
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as server:
            server.starttls(context=context)
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, recipient, msg.as_string())
        log(f"E-POŠTA POSLANA na {recipient} za objavo: {notice['title']}")
    except Exception as e:
        log(f"NAPAKA pri pošiljanju e-pošte: {e}")


def send_ntfy_push(config: dict, notice: dict):
    """
    Pošlje brezplačno takojšnjo potisno obvestilo (Push Notification) na telefon
    preko servisa ntfy.sh (vibrira telefon z zvokom v manj kot 1 sekundi).
    """
    ntfy_cfg = config.get("ntfy_phone_notification", {})
    if not ntfy_cfg.get("enabled", True):
        return

    topic = ntfy_cfg.get("topic", "feri-praksa-ziga-alert")
    if not topic:
        return

    url = f"https://ntfy.sh/{topic}"
    title = f"Nova praksa na FERI: {notice['title']}"
    message = f"{notice['title']}\n{notice.get('date', '')}\nKlikni za ogled!"

    try:
        data = message.encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Title": title[:100],
                "Priority": "5",  # Najvišja prioriteta (takojšnje zvonjenje)
                "Tags": "warning,graduation_cap",
                "Click": notice["url"],
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                log(f"PUSH OBVESTILO POSLANO na telefon preko ntfy.sh/{topic}")
    except Exception as e:
        log(f"Opozorilo pri pošiljanju ntfy obvestila: {e}")


def check_for_updates(config: dict):
    """Izvede en pregled spletne strani in RSS vira."""
    log("Preverjam feri.um.si/praksa/ ...")

    new_notices = []

    try:
        html = fetch_url(URL_PRAKSA)
        has_no_notices, html_notices = parse_html_notices(html)

        # Če v HTML-ju NI niza "Ni obvestil", je nekaj novega
        if not has_no_notices:
            log("POZOR: Na strani NI VEČ napisa 'Ni obvestil'!")
            if html_notices:
                for n in html_notices:
                    if not is_post_seen(n["id"]):
                        new_notices.append(n)
            else:
                # Če se je napis spremenil, a struktura morda drugačna
                pid = "generic-change-" + datetime.now().strftime("%Y%m%d%H")
                if not is_post_seen(pid):
                    new_notices.append({
                        "id": pid,
                        "title": "Stran je bila posodobljena (napis 'Ni obvestil' je izginil)",
                        "url": URL_PRAKSA,
                        "date": datetime.now().strftime("%d.%m.%Y"),
                        "description": "Napis 'Ni obvestil' ni več prisoten na strani. Takoj preveri stran!",
                    })
        else:
            log("Stanje: 'Ni obvestil' (stran je še nespremenjena).")

    except Exception as e:
        log(f"Napaka pri pregledu HTML strani: {e}")

    # Dodatno preveri še RSS vir
    try:
        rss_notices = parse_rss_notices()
        for rn in rss_notices:
            if not is_post_seen(rn["id"]) and not any(n["id"] == rn["id"] for n in new_notices):
                new_notices.append(rn)
    except Exception as e:
        log(f"Napaka pri pregledu RSS: {e}")

    # Pošlji obvestila za vse nove objave
    if new_notices:
        log(f"ZAZNANE NOVE OBJAVE ({len(new_notices)})! Pošiljam obvestila...")
        for notice in new_notices:
            # 1. Pošlji e-pošto
            send_email_alert(config, notice)
            # 2. Pošlji potisno obvestilo na telefon
            send_ntfy_push(config, notice)
            # 3. Zabeleži v bazo, da se ne ponavlja
            mark_post_seen(notice["id"], notice["title"], notice["url"])
    else:
        log("Ni novih objav.")


def run_loop():
    """Glavna neskončna zanka bota."""
    init_db()
    config = load_config()
    interval = config.get("check_interval_seconds", 120)

    log(f"FERI Praksa Notifier Bot je ZAGNAN. Interval preverjanja: {interval} sekund.")
    log(f"Ciljni URL: {URL_PRAKSA}")

    while True:
        try:
            config = load_config()  # Ponovno naloži config, če ga uporabnik uredi med delovanjem
            check_for_updates(config)
        except Exception as e:
            log(f"Nepričakovana napaka v zanki: {e}")

        time.sleep(interval)


def test_alert():
    """Pošlje testno obvestilo za preizkus e-pošte in telefona."""
    config = load_config()
    test_notice = {
        "id": "test-9999",
        "title": "TESTNO OBVESTILO - Bot za prakso deluje!",
        "url": URL_PRAKSA,
        "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "description": "To je testno sporočilo, ki potrjuje, da tvoj notifier bot uspešno pošilja obvestila na tvoj naslov.",
    }
    log("Pošiljam testno e-pošto in push obvestilo...")
    send_email_alert(config, test_notice)
    send_ntfy_push(config, test_notice)
    log("Test zaključen. Preveri svoj e-poštni predal in telefon!")


def test_scrape():
    """Preveri delovanje zajemalnika na arhivski strani (kjer so resnične objave)."""
    log("Testiram zajemalnik na arhivski strani s preteklimi objavami...")
    url_past = "https://feri.um.si/praksa/?p"
    html = fetch_url(url_past)
    pattern = re.compile(r"<article[^>]*id=['\"]post-(\d+)['\"][^>]*>(.*?)</article>", re.DOTALL)
    matches = pattern.findall(html)
    log(f"Najdenih {len(matches)} objav na arhivski strani!")
    for pid, body in matches[:3]:
        tm = re.search(r"<h3[^>]*><a[^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", body)
        title = unescape(re.sub(r"<[^>]+>", "", tm.group(2))) if tm else ""
        log(f" -> Post #{pid}: {title}")


if __name__ == "__main__":
    if "--test-alert" in sys.argv:
        test_alert()
    elif "--test-scrape" in sys.argv:
        test_scrape()
    elif "--once" in sys.argv:
        init_db()
        config = load_config()
        check_for_updates(config)
    else:
        run_loop()
