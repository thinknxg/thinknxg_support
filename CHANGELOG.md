# Changelog

## 1.4.1 — 2026-10-27
* Importer follows the current Helpdesk knowledge-base API (`get_kb_sidebar`, `get_articles`) and falls back
  to older endpoints and REST
* New *Browser Session* access (paste the `sid` cookie) for sites that sign in through single sign-on
* Access errors now quote the source site's own reason and say what to change
* Article link pattern accepts `{slug}`

## 1.4.0 — 2026-10-27
* Built-in knowledge base (*Support Knowledge Article* / *Category*) that works with or without Helpdesk
* One knowledge service for portal, landing page, dashboard and AI assistant (Helpdesk + built-in articles,
  audience-aware: Everyone / Customers)
* Help-article importer: Frappe Helpdesk knowledge-base API (with REST fallback) or page URLs; login or API key
* Rebrand engine with editable rules; code, commands, URLs, e-mails and paths are never changed
* Review workflow: proposals with side-by-side preview and review notes, bulk approve/reject, source-change
  detection that never overwrites published articles
* Licence gate and mandatory attribution on every imported article; optional image copy and link rewriting
* AI assistant indexes built-in articles automatically

## 1.3.0 — 2026-10-27
* Public landing page at `/thinkdesk` with 12 configurable section types (add, remove, reorder, audience, style)
* Configurable header and footer menu links (external or internal, Arabic labels, audience, new tab)
* Public knowledge base for visitors (optional); visitors are sent to log in only for customer pages
* Dashboard moved to `/thinkdesk/dashboard`; choose Landing Page or Dashboard as the customers' home
* Language switch for visitors; chat opens from landing quick actions

## 1.2.0 — 2026-10-27
* AI assistant: provider-agnostic adapter (OpenAI-compatible, Anthropic) with streaming, knowledge retrieval
  (embeddings or keywords) over Helpdesk articles and new Knowledge Snippets, sources, follow-ups, feedback,
  confidence-based handoff, reply limit, daily token budget, redaction, usage logs
* Chatbot: welcome buttons, keyword / phrase / regex / button rules, handoff words, actions (reply, hand off,
  ask AI, create ticket, end chat), numbered options on WhatsApp
* Handoff and routing: chat queues with Least Busy / Round Robin / Manual, agent presence, assignments,
  take over, return to assistant, transfer
* Widget: sender badges, streamed AI replies, quick replies, typing indicators, read receipts, waiting banner
* Agent console: assistant status, filters for "Waiting for agent" and "With assistant", queue filter
* Report: Live Chat Performance

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
