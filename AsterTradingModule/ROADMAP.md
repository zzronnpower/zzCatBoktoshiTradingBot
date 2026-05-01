# AsterTrading Roadmap

Last updated: 2026-05-01

## Mission

Tach rieng phan ASTER futures trading khoi Boktoshi strategy flow va giu van hanh don gian, an toan, de quan ly vi the nhanh.

## Phase 1 - Module Isolation

- [x] Chuan hoa core ASTER logic trong `AsterTradingModule/`.
- [x] Mo rong service de ho tro nhieu symbol trong whitelist.
- [ ] Tach hoan toan ASTER API router khoi `app/main.py` (con lai cho buoc tiep theo).

## Phase 2 - AsterTrading UI Simplification

- [x] Bo `Stop Limit`, chi giu `Market` + `Limit`.
- [x] Bo `Time in force` khoi form giao dich chinh.
- [x] Pair thanh dropdown va dung cung danh sach symbol voi Manual.
- [x] Hien thi preview ro rang: risk, margin, qty, mark + SL reference.

## Phase 3 - AsterSimpleTrading Page

- [x] Them trang moi `/aster-simple-trading`.
- [x] Bo Strategy Control, giu flow mo/dong nhanh.
- [x] Doi `Bot Settings` thanh `Position Settings`.
- [x] Ho tro ca `Close Selected Symbol` va `Close All Positions`.

## Phase 4 - Data Refresh Policy

- [x] Account snapshot chi cap nhat khi bam Refresh.
- [x] Open positions/open orders cap nhat realtime (3s).
- [x] Hai trang ASTER dung chung endpoint vi the/lenh mo de quan ly dong bo.

## Phase 5 - Test & Hardening

- [x] Them unit tests cho Aster service core.
- [x] Them API-level tests cho endpoint `/api/aster-trading/*`.
- [x] Them UI behavior tests cho AsterTrading va AsterSimpleTrading.

## Phase 6 - Operator UX Refinement

- [x] Latest response panel doi sang format de doc cho nguoi van hanh.
- [x] Them nut toggle raw JSON de debug khi can.
- [x] Khi doi pair, preview va quick stats auto-cap nhat ngay.
- [x] Live positions/orders giu tong quan tat ca pair va highlight pair dang chon.
- [x] AsterSimpleTrading chuyen MARKET-only de mo lenh nhanh (bo Order Type/Limit Price).
- [x] AsterSimpleTrading Action Result doi sang structured summary + raw JSON toggle.

## Phase 7 - Connection Diagnostics

- [x] Them endpoint check ket noi xac thuc: `/api/aster-trading/connection-check`.
- [x] Them nut `Check API Auth` tren giao dien AsterTrading.
- [x] Surface goi y xu ly khi gap loi API-key/permission/IP whitelist.

## Phase 8 - Visual Polish Closure

- [x] Hoan thien style chip LONG/SHORT va selected-row highlight tren ca 2 trang ASTER.
- [x] Tinh chinh typography/layout response summary de doc nhanh hon tren desktop/mobile.
- [x] Dong bo visual behavior khi doi pair tren `AsterSimpleTrading` (preview + table context).

## Phase 9 - Global Theme Aster

- [x] Them theme `aster` vao global theme switcher (`default` van giu mac dinh).
- [x] Them token palette + typography/spacing override cho `html[data-theme="aster"]` trong `app/static/app.css`.
- [x] Bat theme switcher tren `AsterTrading` va `AsterSimpleTrading` bang `theme.js`.
- [x] Dong bo style theming tren 2 trang ASTER de an theo theme `aster` ma khong pha vo `default`.

## Phase 10 - Pro API V3 Migration

- [x] Chuyen auth tu flow API key cu sang Pro API (`user`, `signer`, `nonce`, `EIP-712 signature`).
- [x] Chuyen endpoint trading/account sang `/fapi/v3/*`.
- [x] Cap nhat connection-check theo credential Pro API wallet.
- [x] Chuyen market-data client base + endpoint sang V3.

## Phase 11 - Dynamic Symbols + Operator Risk UX

- [x] Pair list cho AsterTrading lay dong tu exchange (`PERPETUAL + TRADING + USDT`).
- [x] `_normalize_symbol` validate theo dynamic tradable set (co fallback khi exchange metadata loi).
- [x] Them card `ACCOUNT OVERVIEW` tren AsterSimpleTrading.
- [x] Them mau canh bao PnL, badge margin ratio, va mini-history 5 snapshot.
- [x] Them estimate line realtime, sync voi backend preview de hien SL/TP price that.

## Phase 12 - Entry/Exit Mode Controls Refinement

- [x] Them checkbox `1% Stoploss (auto from account risk)` trong Position Settings.
- [x] Them RR mode cho TP (1:2, 1:3, 1:4) va tinh TP theo khoang cach risk den stoploss.
- [x] RR mode duoc gate boi checkbox truoc `Take Profit Mode`:
  - [x] checkbox off -> dung TP% manual.
  - [x] checkbox on -> dung RR mode.
- [x] Tinh chinh mau active tab: AsterTrading vang, AsterSimpleTrading cam.
- [x] Them dong thong tin `SL Price % from entry price` de uoc tinh muc cach entry truoc khi vao lenh.
- [x] Lam noi bat dong preview trong MANUAL TRADE PANEL (mau vang + dam) de doc nhanh truoc khi vao lenh.
- [x] Hien thi them `Estimated Entry Price` canh dong SL percent de operator quyet dinh lenh nhanh hon.
- [x] Tach rieng dong `Estimated Entry Price` va dong `SL Price % from entry price`; lam noi bat Entry bang mau vang dam.
- [x] Them `Estimate Side` (LONG/SHORT) de estimate tinh dung theo huong lenh du kien.
- [x] Sua bug dong bo estimate bi hardcode BUY; dong thoi giu nut OPEN LONG/SHORT tach biet voi estimate side.
- [x] Dong bo dong `Preview ... SL ...` trong MANUAL TRADE PANEL theo estimate preview moi nhat.

## Phase 13 - Safety Interaction + Full Visibility

- [x] Bo filter whitelist tinh khi lay open positions/open orders de khong an vi the ngoai list cu.
- [x] Them submit guard cho OPEN LONG/SHORT (disable button + in-flight lock).
- [x] Them trang thai submit ro rang trong UI (idle/submitting/success/failed).
- [x] Them cooldown ngan sau submit thanh cong de giam nguy co double position do spam click.

## Phase 14 - Risk-driven Settings Mode

- [x] Them mode switch trong Position Settings: `Normal Flow Settings` vs `Manual SL, Auto the Rest`.
- [x] Mode `Manual SL, Auto the Rest` nhan input toi thieu: Manual SL Price + % Risk on Total Capital + fixed leverage.
- [x] Backend preview tinh tu dong phan con lai (notional/margin/sl%) theo account risk va khoang cach SL.
- [x] Gioi han `% Risk on Total Capital` toi da 5%.

## Phase 15 - Remaining-slot Auto Leverage

- [x] Trong mode `Manual SL, Auto the Rest`, leverage duoc app tu tinh trong bien `x3..x6`.
- [x] Co che tinh dua tren so slot con lai (`max positions = 3`) va available balance sau buffer.
- [x] Surface metadata runtime (slots, budget/slot, chosen leverage) de operator quan sat.

## Phase 16 - Realtime PnL Readability

- [x] Mau hoa `uPnL` trong bang open positions tren AsterSimpleTrading:
  - xanh khi duong,
  - do khi am,
  - cap nhat theo poll realtime 3s.

## Phase 17 - Open Orders Semantic Clarity

- [x] Dieu chinh cot open orders de phu hop lenh SL/TP market close:
  - hien `stopPrice` o cot gia trigger,
  - hien `Close-All` cho lenh `closePosition=true` thay vi qty=0,
  - bo sung SL/TP badge o cot Type.
- [x] Bo sung context `symbol + side` (va `orderId` neu co) trong submit status de de theo doi lenh nhanh.

## Ongoing Rule

Sau moi batch code cua ASTER scope, cap nhat dong thoi:

- `AsterTradingModule/ROADMAP.md`
- `AsterTradingModule/CHECKLIST.md`
- `PROJECT_LOG.md`
- `app/templates/chatlog.html`
