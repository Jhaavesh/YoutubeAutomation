# Don Of Vice City — Auto-Pilot Rules (Verified Behavior)

Ye document batata hai ki pipeline **actually kya karta hai**. Ye marketing
claims ya legal guarantees nahi hain.

---

## Rule 1: Source deduplication (not a copyright license)

- Har downloaded source video ki YouTube ID `used_source_ids` me save hoti hai.
- Same ID dobara milne par script next search result choose karti hai.
- Ye sirf **repeat source avoidance** hai. Ye footage ko legal, licensed, ya
  copyright-safe nahi banata.
- Har Short ke liye alag source lene ki koshish hoti hai, lekin search results
  limited ho sakte hain. Failure par video skip ho sakti hai; run falsely
  success report nahi karega.

---

## Rule 2: Audio behavior (current implementation)

- Source clip ka original audio **replace** hota hai, mix nahi hota.
- Configured background track (`assets/audio/`) loop hota hai aur
  `video.short.audio_volume` / `video.long.audio_volume` se volume set hota hai.
- “Scene ke hisaab se sound change” ya “70% original audio” abhi implemented
  nahi hai. Aisa claim na karein.
- Sirf aisa music use karein jiska aapke paas monetized YouTube use ke liye
  license ho.

---

## Rule 3: Visual hooks and typography

- Vertical Shorts par top hook text, bottom secondary text, aur channel
  watermark `drawtext` se lagta hai.
- Font `video.fonts.primary` se aata hai; na milne par fallback, phir FFmpeg
  default.
- Text sanitize hota hai taaki FFmpeg filter syntax break na ho.
- Hook pehle frame se visible hota hai; koi separate 2-second intro delay nahi.

---

## Rule 4: Video standard

- Shorts: `1080x1920` (9:16), duration `26s` by default.
- Long video: `2560x1440` (16:9), duration range `150–180s`.
- Frame rate config se enforce hota hai (`video.*.fps`, currently 60).
- Output H.264 + AAC, `yuv420p`, `+faststart`.
- Bitrate quality CRF/preset par depend karti hai; “high bitrate guaranteed”
  claim sahi nahi hai.

---

## Rule 5: Daily schedule

Configured standard slots (Asia/Kolkata):

- Slot 1 — 1:00 PM
- Slot 2 — 4:30 PM
- Slot 3 — 7:30 PM
- Slot 4 — 10:30 PM
- Long video — 6:00 PM

Agar bot late start hota hai:

- Past slots skip hote hain.
- Bache hue Shorts current time se end-of-day (11:30 PM) ke beech spread hote
  hain.
- Long video `now + min_lead_minutes` par schedule hota hai.
- **Koi guarantee nahi** ki har video publish hogi. Quota, network, API error,
  ya upload failure par run fail ho sakta hai; exit code non-zero aayega.

---

## Rule 6: Cleanup and disk use

- Raw download render ke baad delete hota hai.
- `daily_generated/` me rendered files `cleanup.max_age_hours` (default 24h) ke
  baad delete hote hain.
- Iska matlab daily output temporarily sainkron MB le sakta hai. “Disk kabhi
  bhi 50–100 MB se zyada nahi” claim galat hai.
- `daily_generated/` ko manually clean karna safe hai jab koi run na chal raha
  ho.

---

## Rule 7: Publishing and approval

- Default: `approval.required: false`, `auto_approve: true`. Videos private
  upload hoti hain aur `publishAt` ke saath schedule hoti hain.
- `approval.required: true` hone par video **private draft** rehti hai;
  `publishAt` attach nahi hota; metadata se public/unlisted karna block hota
  hai.
- Upload se pehle FFprobe validation hoti hai.
- Same file bytes + same channel dubara upload karne par ledger existing video
  ID return karta hai (unless forced).

---

## Rule 8: Compliance (important)

- Current pipeline third-party YouTube footage download karke re-upload karta
  hai. Ye copyright/license risk hai.
- `source_policy.rights_confirmed` default `false` hai aur engines warning
  log karte hain.
- Sirf owned, licensed, ya legally usable footage publish karein.
- Titles/descriptions me ye claim na karein ki footage official GTA VI gameplay
  hai jab tak wo sach na ho.
- Ye project views, monetization, ya copyright safety guarantee nahi karta.
