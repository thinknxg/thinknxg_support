# Changelog

## 1.1.2 — 2026-10-26
* Portal moved to `/thinkdesk` (guest chat: `/thinkdesk/chat`). ERPNext's `/support` page is still left untouched

## 1.1.1 — 2026-10-26
* Portal moved from `/support` to `/customer-support` (guest chat: `/customer-support/chat`) so it no
  longer clashes with ERPNext's built-in `/support` page. Page files renamed to
  `www/thinknxg_support_portal.*` and `www/thinknxg_support_chat.*`
* The website chat launcher now also appears on ERPNext's `/support` page; inside the portal it is still
  mounted by the portal itself

## 1.1.0 — 2026-10-24
* Live chat: "Chat with support" widget in the portal, on public website pages and at `/thinkdesk/chat` for guests
* Guest chats with hashed session tokens, per-IP limits, honeypot, email of missed replies, retention purge
* WhatsApp Cloud API: signed webhook, inbound text/media, contact matching, 24-hour window handling with
  template fallback, delivery receipts, retries, out-of-hours auto reply, "Chat on WhatsApp" button
* Agent chat console (`/app/support-chat`) with realtime updates for portal, live chat and WhatsApp
* New conversation channel field; guest and WhatsApp details on conversations

## 1.0.0 — 2026-10-24
* First release: unified `/support` portal (Vue 3, EN/AR, light/dark, responsive)
* Helpdesk adapter with runtime schema detection; Raven bot bridge with loop prevention; ERPNext read-only views
* 12 DocTypes, 6 roles, capability-based access, audit events, rate limiting, download grants
* Integration and security test suite
