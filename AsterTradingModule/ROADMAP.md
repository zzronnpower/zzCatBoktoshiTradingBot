# AsterTrading Roadmap

Last updated: 2026-03-04

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

## Ongoing Rule

Sau moi batch code cua ASTER scope, cap nhat dong thoi:

- `AsterTradingModule/ROADMAP.md`
- `AsterTradingModule/CHECKLIST.md`
- `PROJECT_LOG.md`
- `app/templates/chatlog.html`
