# Changelog

## 1.15.0, 2026-11-11 — alerts when the app is not open
* **Windows app**: starts with Windows in the background (installer option, on by default), stays in the system
  tray when its window is closed, keeps receiving alerts and shows Windows notifications with sound; clicking one
  opens the record. A second start brings the running app forward. Switches in the Alerts tab.
* **macOS app** (new): the same workspace, in the menu bar, started at sign-in by a Launch Agent; with a signed
  build, push through Apple's notification service (also when the app is not running) and a dock badge.
* **Android and iOS**: icon badges with the number of waiting alerts; the Alerts tab says when notifications are
  off or (Android) battery saving can hold alerts back, and opens the system settings.
* **Push service**: every push is tracked (*Support Push Delivery*: Sent, Opened, Retrying, Failed, Token Removed)
  and retried for a few minutes when Firebase cannot be reached; macOS devices; the badge count.
* Staff API: `push_opened`; `register_device` accepts `macOS`.

## 1.14.2, 2026-11-10
* **A lead for every website chat**: when a visitor fills in the start-chat form, a lead is created automatically
  (Support Portal Settings > Leads > "Create a Lead When a Visitor Starts a Chat", on by default; needs "Create Leads
  In" not Off). If a lead with the same e-mail address exists, the chat is linked to it and its blank fields (phone,
  name) are filled in; nothing already on the lead is overwritten. The form details and first message go on the
  lead's timeline. Runs in the background, so the chat never waits for it.

## 1.14.1, 2026-11-08
* Fix: **Log out** in the support portal gave "Not Permitted" (Frappe v16 only accepts logout as a POST). The portal
  now posts to `/api/method/logout` and returns to the portal home.

## 1.14.0 — increment 3 of 3, 2026-11-08
* **Leads from chats**: in thinkNXG CRM (CRM Lead) when it is installed, otherwise ERPNext Lead (Support Portal
  Settings > Leads; "Off" switches it off). From the web console, the apps, lead capture or automation rules. An
  existing lead with the same e-mail or phone is linked, not duplicated. The chat and, later, its outcome appear on
  the lead's timeline.
* **Lead capture** in the chat: the assistant asks for name, e-mail, phone and company one question at a time
  (chatbot rule action "Collect Details", automation rule, or an agent's "Collect details"); "cancel" stops it, and
  agents who have taken the chat are never interrupted.
* **AI lead score** (Support AI Settings > Score Leads, off by default): 0 to 100 with reasons, on the chat.
* **Automation rules** (*Support Automation Rule*): a message on a page after N seconds (website chat), a quiet
  customer (nudge, close, or notify / escalate), a chat closed needing follow-up (a to-do or an escalation), a new
  chat outside chat hours (a message or lead capture instead of the offline message). Runs are logged
  (*Support Automation Run*) and counted on the analytics page with leads from chats and conversions.
* Staff API: `create_lead`, `collect_lead_details`; `lead` on conversations; `capabilities.leads`.

## 1.14.0 (in progress) — increment 2 of 3, 2026-11-08
* **Agent status**: Available, Away, Busy or Offline, set in the web console and the apps. Only Available agents get
  new chats; Away and Busy agents keep theirs; Offline agents are also not rung for queue chats. Away also comes
  automatically after idle minutes (Support Portal Settings > Agent Status, default 10; older apps never go Away).
* **Shifts** (*Support Agent Shift*): a weekly schedule per agent, overnight shifts included; off shift counts as
  Offline. Agents without a status or a shift work exactly as before.
* **Priority** (Low, Normal, High, Urgent) set by people, separate from the AI's urgency; inbox "Priority first".
* **Tags** on conversations, using Frappe's own tags (desk list filters and the sidebar work with them).
* Staff API: `set_status`, `team_status`, `heartbeat(active)`, `set_priority`, `set_tags`, `tag_suggestions`,
  `conversations(sort, priority, tag)`; `priority` and `tags` on conversations; `status` in bootstrap.

## 1.14.0 (in progress) — increment 1 of 3, 2026-11-08
* **Reply to a message** with a quote, in the chat widget, the web console and the agent apps; also on WhatsApp.
* **Edit and remove messages**: staff their own while the chat is open; customers and visitors their own within the
  edit window (5 minutes by default). Every earlier version is kept for staff; removed messages show "Message
  removed" to customers and stay in the record. WhatsApp messages cannot be changed once sent.
* **Reactions** (👍 ❤️ 😂 😮 😢 🙏), also to and from WhatsApp.
* **Files for visitors** (off by default) and **voice notes** (widget, console and apps), with photo previews and
  inline playback. Downloads are checked again every time.
* **WhatsApp media**: images, documents and AAC / MP3 / OGG voice notes go out through the Cloud API, with the reply
  context.
* **Fix**: file downloads (portal documents, chat and ticket attachments) are now sent exactly as stored; before,
  some binary files (such as PNG images) could arrive damaged.
* Settings: Support Portal Settings > Chat Messages. New DocType Support Message Revision. Staff API: `edit_message`,
  `remove_message`, `react`, `message_history`, `reply(reply_to, voice_seconds)`, `messages(changed_since)`.

## 1.13.0 — 2026-11-08
* **Support Analytics** page: live waiting, active chats and visitors; AI resolved vs human, AI resolution rate,
  first response and resolution times, satisfaction, AI usage, mood, intents, languages, handoff reasons and agent
  performance, by period, channel and queue. Managers only; cached; new indexes for its queries.
* **Privacy requests**: export or erase one person's chat data, with identity confirmation, counts-only audit and a
  list of linked records elsewhere.
* **Security check** with two-factor guidance and a one-click requirement for the support roles.
* **Usage limits per site**: hosting caps in `site_config.json`, lower limits in *Support Usage Limits*, enforced for
  AI tokens, guest chats, knowledge documents and storage, websites and crawled pages.
* Release 1.12 (messaging, CRM and automation) is still to come; lead figures join the analytics with it.

## 1.11.0 — 2026-11-08
* **Knowledge base uploads** (*Support Knowledge Document*): PDF, Word, Excel, CSV, text, Markdown and HTML files
  become knowledge for the assistant and the copilot. Files stay private; documents are staff-only until you choose
  another audience. Clear errors for scanned or damaged files.
* **Website crawling** (*Support Knowledge Website*, *Support Knowledge Web Page*): your help site or website in the
  knowledge base, refreshed daily or weekly. robots.txt, noindex, one site only, no internal addresses, size limits.
* **Multilingual answers**: language detection, search across languages, answers in the customer's language and
  translated fixed messages (Support AI Settings > Knowledge > Languages).
* New *Staff* audience for knowledge, used only by the agent copilot. Existing articles, snippets, the article
  importer and their audiences are unchanged. Patch `v1_11.knowledge_defaults` stores the new defaults.

## 1.10.0 — 2026-11-08
* **AI agent copilot** (web console "AI assist" menu, and the AI button / Ctrl+I in the Windows, Android and iOS
  apps): suggested replies grounded in the knowledge base, rewrite (professional, friendly, shorter, fix grammar),
  translate the draft into the customer's language or the customer's message into yours, recommended solution and
  questions to ask, conversation summary, and "Add summary note" (internal). Everything is a draft; nothing is sent
  without the agent.
* **Message insight** (off by default: Support AI Settings > Analyse Customer Messages): intent, sentiment,
  frustration, urgency and language for each customer message, rolled up on the conversation, shown as pills in the
  inbox and chat header. Frustrated or urgent negative messages raise the new "Frustrated Customer" alert and,
  when switched on in Support Escalation Settings, a "Negative Sentiment" escalation.
* **Assistant style and memory**: tone, persona and how many earlier messages the assistant reads.
* **Handoff summary**: when the assistant hands a chat to people, an internal summary note is added.
* Staff API: `copilot` method, `insight` on conversations. All AI calls use the existing provider, daily budget,
  usage log and contact-detail redaction. Patch `v1_10.ai_copilot_defaults` stores the new defaults; no data changes.

## 1.9.0 — 2026-11-06
* **thinkNXG Support Agent apps** (Windows, Android, iOS; one Flutter codebase in `agent_app/`): sign in with the
  staff account in the browser (OAuth + PKCE), inbox for Portal / Live Chat / WhatsApp, claim, reply, internal
  notes, transfer, End chat with wrap-up, Helpdesk tickets (reply, note, status, priority, assign), alerts
* **Staff API v1** (`thinknxg_support.api.staff.v1`, documented in `docs/agent-api.md`): versioned, paginated with
  stable cursors, per-agent read state, atomic claim (one winner, 409 for the other), duplicate-safe replies
  (client request id), queue visibility applied to lists and direct lookups alike, Helpdesk permissions for tickets
* **Support Agent App Settings**: switch the apps on or off, sign-in addresses, polling intervals, one-click OAuth
  client (public client, staff roles only)
* New records: Support Agent Read State, Support Agent Device, Support Agent Request (idempotency log)
* Unique index on (conversation, client message id) for messages
* Full agent workspace in the apps: canned responses with placeholders, attachments (send one per message, open after
  a per-file access check), transfer picker (agents online first, queues), customer history, typing and visitor
  presence, ticket team changes, details sheet on phones
* Alerts in the apps with the web alert centre's sounds and rules, device notifications, offline banner and refresh
  on reconnect
* **Push notifications** (Firebase / APNs) for agent alerts: generic lock-screen text, record opened only after the
  server re-checks access, dead device tokens switched off; *Send Test Push to Me* in Support Agent App Settings
* Packaging: Windows installer (Inno Setup, signed when a certificate is configured), Android APK + App Bundle,
  signed iOS build uploaded to TestFlight when Apple signing is configured
* Agents (console and apps): **Create ticket** from a chat (priority, team, type, optional first reply with a
  Helpdesk saved reply), **Link customer** (suggested from the visitor's e-mail/phone, add the visitor as a contact),
  **HD Saved Reply** picker in ticket replies
* End chat always asks *Was the customer's issue resolved?* and *Does the customer need a follow-up?* (Yes/No,
  required), also stored on the conversation (*Issue Resolved*, *Needs Follow-up* filters)
* Fix: customers are registered as **HD Customers** (with their contacts) when created or changed, not only when
  they raise a ticket; existing support customers are backfilled
* Fix: live chat messages in chats without a queue now alert agents (they reached nobody); apps check every 5 s
* CI: Flutter analyse / test / Windows, Android and iOS builds; backend tests on a Frappe v16 bench with Helpdesk

## 1.8.0 — 2026-11-06
* **Post-chat feedback survey**: 1–5 star agent rating (Excellent … Very Poor), issue resolved (Yes / Partially /
  No) and comments; shown in the chat widget when a chat closes and sent as a link on WhatsApp; Off / Optional /
  Required; comments required for low ratings (configurable)
* **Support Chat Feedback** linked to chat, agent, queue and customer; supervisors see all, agents their own
* Negative feedback alerts and e-mails to supervisors; positive feedback alerts to the agent (alert centre)
* **Agent CSAT** report by agent, week or month; feedback number cards on the Support Query Management workspace
* Fix: alert sounds did not play. Sound is now unlocked in each tab on the first click or key press, only a tab with
  sound allowed rings (the tab in use takes over), alerts arrive by polling when live updates are down, and the
  Administrator account gets alerts. New **Check Alerts** diagnostics and a server-sent test alert
* Fix: *Escalate to Team* on a chat or ticket that was already escalated failed with
  "'str' object has no attribute 'name'"; it now raises the escalation level
* Fix: the audit log (`/app/support-portal-event`) said "Page not found": the DocType was flagged *read_only*
  ("User Cannot Search"), which hides it from the desk

## 1.7.1 — 2026-11-06
* Fix: visitors' live chat messages showed their HTML tags ("<p>When will you be available?</p>") to agents and the
  assistant. The widget sends simple HTML; guest messages are now turned back into text before saving
* Patch repairs visitor messages already saved that way

## 1.7.0 — 2026-11-06
* **Alert centre** on every desk page for new chats, chat messages, new tickets, ticket assignments, conversation
  messages and escalations: distinct pop-ups and sounds, repeat until acknowledged or picked up, one ringing tab,
  background-tab timing on the audio clock, system notifications, title badge
* **Support Alert Settings** (team defaults per activity) and **My Alert Preferences** (per agent: mute, volume,
  sound, pop-up, repeat, test sounds); custom sound files
* **Support Agent Alert** log and **Agent Alert Response** report (time to acknowledge, picked up, missed)
* **Canned responses**: categories, `/shortcut` typeahead and picker in the chat console, placeholders, edit before
  sending, private or team, usage counts; Helpdesk canned responses included
* **End chat** wrap-up: closure reason, configurable wrap-up questions, notes, optional closing message; saved on the
  conversation and in its history
* Escalation pop-ups now use the alert centre (Escalation sound)

## 1.6.0 — 2026-11-05
* Landing page: *Popular Articles* grouped by knowledge-base category for visitors and customers, most-read first
  (reads + helpful votes, or Helpdesk views); *Items to Show* = articles per category (new installs: 4)
* Built-in articles count reads (once per reader per 6 hours)
* **Support Escalation**: one record per escalated chat, conversation or ticket, with status (New, Pending,
  In Progress, Resolved, Closed), priority (Critical–Low), assignment, team, escalation level, response and
  resolution targets, overdue flags, escalation history, internal notes and customer interaction history
* Escalations raised automatically on AI handoff, customer asking for a person, chats that start with people,
  conversation and service-request escalation, urgent Helpdesk tickets and SLA breaches; manual **Escalate to Team**
* Notifications on new, further-escalated, reassigned and overdue escalations: in-app pop-up with sound, notification
  center, email, WhatsApp (template or plain text)
* **Support Query Management** workspace: six indicators, three charts, Support Chat / Conversation / Support Tickets
  sections with counts and live lists
* **Support Escalation Settings**: triggers, default priorities, targets, channels, recipients, overdue alerts

## 1.5.1 — 2026-11-01
* Fix: AI assistant replies showed "Iâ€™m" / "donâ€™t" instead of "I’m" / "don’t" (and broke Arabic). Providers stream
  `text/event-stream` without a charset, so the reply was decoded as ISO-8859-1; each line is now decoded as UTF-8
* Patch repairs assistant and bot messages already saved with the garbled text

## 1.5.0 — 2026-10-28
* Knowledge base: category sidebar with article titles (wiki style, filter, mobile fold-out)
* Copy link button on every article
* "Was this article helpful?" thumbs up / down with optional comment; *Support Article Feedback* records,
  vote totals on built-in articles; one vote per reader, rate limited
* "If your issue isn't resolved, raise a support ticket here": pre-filled ticket (title + article link);
  visitors log in first; chat option when live chat is on
* Related articles (same category, then similar titles), audience-aware
* *Sort Order* on built-in articles for the sidebar
* API: `knowledge.sidebar`, `knowledge.related`, `knowledge.feedback`; `knowledge.article` returns `my_vote`

## 1.4.2 — 2026-10-28
* Website and e-mail rebranding rules on each knowledge source (*Support Link Rule*): links, plain-text web
  addresses and e-mail addresses move to thinkNXG sites, longest match first, optionally keeping the path
* Default rule `docs.frappe.io/erpnext` → `https://docs.thinknxg.com/thinknxgerp`; other Frappe sites listed, off
  until a thinkNXG address is entered
* **Apply Link Rules to Published Articles** updates live articles; attribution footers keep the original links
* The "Frappe websites" and "Frappe e-mail" review notes now check the rebranded text, so they clear once rules cover them

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
