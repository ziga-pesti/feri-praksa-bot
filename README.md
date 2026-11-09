# FERI Praksa Notifier Bot 🚨

Avtomatski 24/7 sistem za spremljanje spletne strani [https://feri.um.si/praksa/](https://feri.um.si/praksa/) z dvojnim sistemom takojšnjega obveščanja:
1. **E-poštno opozorilo (Gmail / SMTP):** Pošlje podrobno HTML sporočilo z naslovom, datumom in neposredno povezavo do nove objave.
2. **Takojšnje potisno obvestilo na telefon (ntfy.sh):** Vibrira in zazvoni na telefonu v manj kot 1 sekundi po zaznavi.

---

## ⚡ Hitra nastavitev v 2 korakih

### 1. Korak: Nastavitev Gmail gesla za aplikacije v `config.json`
Ker ima Google vklopljeno 2FA zaščito, za pošiljanje e-pošte potrebuješ t.i. **App Password**:
1. Odpri [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. Vpiši ime (npr. `FERI Bot`) in klikni **Ustvari / Create**.
3. Google ti izpiše 16-mestno geslo (npr. `abcd efgh ijkl mnop`).
4. Odpri datoteko `config.json` in to geslo prilepi v polje `"smtp_password"`:
   ```json
   "smtp_password": "tvoje-16-mestno-geslo"
   ```

### 2. Korak: Vklop takojšnjih obvestil na telefonu (Brezplačno, brez registracije)
1. Na telefon (iOS ali Android) si naloži brezplačno aplikacijo **ntfy** (ali odpri v brskalniku [https://ntfy.sh](https://ntfy.sh)).
2. Klikni **+ (Subscribe)** in vpiši temo:
   `feri-praksa-ziga-alert`
3. Takoj ko bot zazna kakršnokoli objavo, bo tvoj telefon zazvonil in prikazal obvestilo!

---

## 🧪 Preizkus delovanja

Pred zagonom lahko delovanje preizkusiš s testnimi ukazi:

```bash
# Preizkus pošiljanja testnega obvestila na e-pošto in telefon:
python3 praksa_bot.py --test-alert

# Preizkus zajemalnika na arhivski strani (kjer so resnične pretekle objave):
python3 praksa_bot.py --test-scrape

# Enkratni pregled trenutnega stanja v živo:
python3 praksa_bot.py --once
```

---

## 🚀 Zagon v ozadju (24/7 delovanje)

### Možnost A: Na tvojem Macu (preko macOS Launchd storitve)
Bot bo samodejno tekel v ozadju Maca, se zagnal ob vsakem vklopu in se samodejno ponovno zagnal ob morebitni prekinitvi:
```bash
./start_mac_background.sh
```
Za zaustavitev kadarkoli:
```bash
./stop_mac_background.sh
```

Spremljanje dnevnika v živo:
```bash
tail -f bot.log
```

### Možnost B: Na domačem Homelab / Proxmox Linux strežniku (Docker)
Mapo preprosto kopiraš na domači strežnik in zaženeš:
```bash
docker compose up -d
```
