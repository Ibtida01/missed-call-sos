# Missed Call SOS

Crisis telemetry that runs on unanswered phone calls.

One real phone number. Someone in a flooded village calls it and hangs up
before it's answered — free, since the call is never picked up. Call again
within the time window and the system reads it as more urgent: once for
"water's rising," twice for "we're evacuating," three times for "need rescue."
The ring itself carries who called, how urgent it is, and when. Those signals
land on a live map in seconds.

No app. No mobile data. No smartphone. No cloud phone bill. Works on a ৳800
button phone calling a real Teletalk SIM.

---

## What's in here

```
missed-call-sos/
├── backend/
│   ├── main.py           FastAPI: MacroDroid endpoint, SQLite, WebSocket fan-out
│   ├── config.json       severity numbers, labels, caller registry, upazila coords
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.jsx
│       ├── App.jsx       map + switchboard + live log
│       └── styles.css
└── README.md
```

---

## 1. Run the backend

**macOS / Linux**

```bash
cd missed-call-sos/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Windows (PowerShell)**

```powershell
cd missed-call-sos\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Check it:

```bash
curl http://localhost:8000/health
```

Fire a fake call without any phone at all:

```bash
curl -X POST http://localhost:8000/api/simulate -H "Content-Type: application/json" -d "{\"severity\":3}"
```

## 2. Run the dashboard

In a second terminal:

```bash
cd missed-call-sos/frontend
npm install
npm run dev
```

Open http://localhost:5173. Press **Ring line 3** and a red pin should pulse onto
the map while the whole console flares. If that works, the hard part is done —
everything after this is plumbing a real phone into the same path.

## 3. Wire up your real Teletalk number (free path, no Twilio, no card)

One SIM only has one number, so instead of three separate lines, severity comes
from **how many times in a row someone calls**: once = water rising, twice
within the time window = evacuating, three times = need rescue. This is the
free, real-phone path — no cloud telephony bill, no trial-account limits.

**What you need:** a spare Android phone with your Teletalk SIM in it (any
phone that can receive calls and has Wi-Fi or a little mobile data), and the
free app **MacroDroid**.

### 3.1 — Install MacroDroid on the phone with the SIM

```
Play Store → search "MacroDroid" → install (free tier is enough)
```

### 3.2 — Get your backend reachable from that phone

If the phone and your laptop are on the same Wi-Fi, find your laptop's local IP:

```bash
# macOS / Linux
ifconfig | grep "inet " | grep -v 127.0.0.1
# Windows
ipconfig
```

You'll get something like `192.168.1.42`. Your endpoint is then:

```
http://192.168.1.42:8000/api/macrodroid
```

If the phone is on mobile data instead (recommended for the actual demo, since
venue Wi-Fi is unreliable), tunnel your backend publicly instead:

```bash
npm install -g ngrok
ngrok config add-authtoken YOUR_NGROK_TOKEN
ngrok http 8000
```

Use the `https://xxxx.ngrok-free.app/api/macrodroid` URL it prints.

### 3.3 — Build the MacroDroid macro

Open MacroDroid → **Add Macro**.

**Trigger:**
1. Tap **Add Trigger → Phone → Call Missed** (or **Call Screening / Phone State**
   depending on your MacroDroid version — pick whichever fires the moment a
   call ends unanswered).
2. Leave the number filter blank so it fires for anyone.

**Action:**
1. Tap **Add Action → Connectivity → HTTP Request**.
2. Method: **GET**
3. URL:
   ```
   http://192.168.1.42:8000/api/macrodroid?caller=[caller_number]
   ```
   Replace `192.168.1.42:8000` with your ngrok URL if you're tunneling.
   `[caller_number]` is a MacroDroid **magic text / local variable** — tap the
   `{ }` icon next to the URL field and pick the caller's number from the
   trigger's available variables. The exact label varies by MacroDroid
   version (`lv_phone_number`, `cr_phone_number`, or similar) — whatever it's
   called, it inserts the number that just called.
4. Save the macro, name it "Missed Call SOS relay".

### 3.4 — Test it before you trust it

1. From a second phone, call your Teletalk number and hang up before it's
   answered.
2. Watch the dashboard. A pin should appear within a couple of seconds.
3. Call again immediately (within 90 seconds) — the same pin should escalate
   to level 2, then level 3 on a third call.

If nothing happens: open MacroDroid's macro, tap the three-dot menu →
**"Test macro"**, and check the **HTTP Request** action's response — it'll show
you the exact error (usually a wrong IP, or the phone not actually on the same
network as your laptop).

### 3.5 — Put your real number on the dashboard

Edit `backend/config.json`:

```json
"teletalk_number": "+8801XXXXXXXXX",
```

Restart uvicorn. The dashboard now shows your real number as the one to call.

---

### Optional: still want Twilio numbers too?

The backend still has a `/voice` webhook and `severity_by_number` config left
in for exactly this — if you later want extra lines (e.g. English vs Bangla,
or a second responder line), you can add Twilio numbers back in alongside the
Teletalk line without removing anything. Not necessary for the demo though.

## 4. Register a few callers

`config.json` → `caller_registry` maps a phone number to a place id. Put your own
number and a couple of friends' numbers in there so their pins land in real
upazilas. Anyone who calls without being registered still shows up — the backend
hashes their number to a place deterministically and tags the pin
**unregistered** so the map never claims a location it doesn't have.

---

## Three things that can kill your demo — deal with them on day one

**1. The relay phone needs to stay awake and connected.** Android will happily
kill background apps to save battery, including MacroDroid's ability to catch
the missed-call trigger reliably. In MacroDroid, go to the macro's settings and
disable battery optimisation for the app (Android will prompt you, or find it
under **Settings → Battery → Unrestricted** for MacroDroid). Test this an hour
before you present, not five minutes before — battery-saving kills are
inconsistent and only show up after the phone's been idle a while.

**2. Same-Wi-Fi setups break the moment you change rooms.** If your backend URL
is a local IP like `192.168.1.42`, it stops working the second either phone
switches networks — which happens constantly at a venue. Use the ngrok tunnel
(or deploy to Render, see below) so the URL stays valid regardless of which
Wi-Fi either device is on.

**3. MacroDroid's variable name for "caller number" varies by version.** If your
HTTP Request comes through with an empty caller, open the macro, tap into the
URL field, and re-pick the variable from the trigger's own variable list rather
than typing it from memory — the exact tag changes between MacroDroid releases.
Test this on day one so you're not debugging it live.

**Fallback that always works:** the on-screen **Ring line** buttons write to the
exact same database and WebSocket as a real call. If the phone, the Wi-Fi, or
MacroDroid misbehaves mid-demo, keep going with the buttons — the audience
can't tell the difference on the dashboard, and you still demonstrate the real
architecture verbally.

---

## Deploy it (so the demo doesn't depend on your laptop or the venue wifi)

**Backend → Render**

1. Push this repo to GitHub.
2. Render → New → Web Service → connect the repo.
3. Root directory `backend`, runtime Python.
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Take the resulting URL and update the MacroDroid action's URL to
   `https://your-app.onrender.com/api/macrodroid?caller=[caller_number]`,
   replacing the ngrok URL. This is the version you actually want live at the
   event — it works regardless of which Wi-Fi the relay phone is on.

Render's free tier sleeps after inactivity and takes ~40s to wake. Hit the URL
once right before you present.

**Frontend → Vercel**

```bash
cd frontend
npm install -g vercel
vercel
```

Set the env var `VITE_API_BASE` to your Render URL in the Vercel dashboard, then
`vercel --prod`.

SQLite on Render's free tier resets when the instance restarts. Fine for a demo.
If you want calls to survive, swap the connection for Postgres — but only after
everything else works.

---

## Build order

If you run short on time, stop anywhere after step 3 and you still have a demo.

1. Backend running, `/api/simulate` writing rows — **the demo exists from here**
2. Dashboard rendering the map and log from those rows
3. WebSocket wired, pins appearing live
4. Teletalk number + MacroDroid → real call → real pin
5. Deployed, so it survives the venue network
6. Polish: sound on a level-3 call, a 30-second replay of a stored surge, an
   auto-generated rescue list sorted by severity then time

---

## Demo script (90 seconds)

> "During the 2024 floods, people in Sunamganj had phones with a signal but no
> data and no way to tell anyone anything. This is what they could have used —
> and this number on screen is a real Teletalk SIM, not a rented cloud number."

1. Show the empty console. Point at the single number on the left.
2. Call it from your own phone and hang up before it's answered. The pin
   lands at level 1. **"That call was never answered. It cost the caller
   nothing. It's already on the map."**
3. Call the same number again, right away. **"Same number, called twice — the
   system reads that as escalation, the same way calling someone twice already
   means 'this is urgent' here."**
4. Call a third time. The pin turns red, the rescue counter increments.
   **"Three calls, no app, no data, no menu to navigate under stress."**
5. Use **Ring line 2 / 3** buttons to fill the map with a wider surge if you
   want the room to feel the scale, then close on the constraint: **"The only
   skill required is dialling a number they already know how to dial."**

---

## Questions a judge will ask, and honest answers

**Isn't calling three times awkward or easy to mess up under panic?**
It's simpler than remembering three different numbers, and it mirrors an
existing habit — calling twice to signal urgency is already common practice
here. The window is configurable (`repeat_window_seconds` in `config.json`, default
90s), so it's forgiving of someone re-dialling a little slowly.

**How do you know where the caller is?**
Registered callers tie their number to a union/upazila once, by SMS or through a
local volunteer — the same way mobile financial services already onboard people
here. Unregistered callers show up flagged as unlocated rather than silently
faked. At real scale, the operator's cell-tower data gives coarse location
without any registration, which is exactly the kind of thing a telco
partnership unlocks.

**What stops someone spamming it?**
Right now, nothing beyond the repeat-call window itself. The next layer is
rate-limiting per number over a longer horizon, and weighting by how many
*distinct* numbers report the same area — one phone crying wolf looks very
different from forty phones in one union.

**How does this become real?**
A shortcode or a BTRC-registered service number from a telco, so any caller on
any network can reach it for free, the way commercial missed-call services
already work here. The demo already runs on a real SIM — the only thing
missing for scale is the operator's cooperation, not new technology.

**Why not SMS?**
SMS costs money, needs literacy and a keypad the caller can navigate under
stress, and queues badly when networks are congested. A missed call is one
button, free, and gets through when everything else is saturated.

---

## Notes

- Caller numbers are masked on screen. The raw number stays in SQLite and is
  never sent to the browser.
- Upazila coordinates in `config.json` are approximate centroids, fine for a map
  demo. Swap in exact boundaries from geoBoundaries or HDX if you want to claim
  precision.
- `allow_origins=["*"]` is set for convenience. Narrow it before this touches
  anything real.
