# thinkNXG Support

Unified, branded customer service portal for **thinkNXG ERP (ERPNext) v16**, bringing together
**Frappe Helpdesk** ticketing, **Raven** messaging and ERPNext self-service at `/thinkdesk` — without
exposing the desk UI and without duplicating Helpdesk or Raven records.

| Concern | Source of truth | thinkNXG Support role |
|---|---|---|
| Customers & contacts | ERPNext / Frappe Contact | Resolve identity and access |
| Tickets, replies, SLA, KB | Frappe Helpdesk (`HD Ticket`, `HD Article`) | Unified ticket UI via adapter |
| Team chat | Raven | Private agent channel per conversation via bot bridge |
| Orders, invoices, payments | ERPNext | Read-only, field allow-listed views |
| Portal preferences, links, audit | thinkNXG Support | Its own 12 DocTypes |

## Requirements

* Frappe Framework / thinkNXG Framework **v16**, ERPNext **v16** (required — identity resolves to `Customer`)
* Optional: Frappe Helpdesk (tickets + knowledge base), Raven (agent messaging bridge)
* Node 18+ (bundled by `bench build`; uses Vue 3, already present in Frappe's toolchain)

The app installs and runs **without** Helpdesk or Raven. Missing integrations show an
administrator notice in the portal and on *Support Portal Settings*; customers see a friendly
"temporarily unavailable" message and the rest of the portal keeps working.

## Install

```bash
cd frappe-bench
bench get-app /path/to/thinknxg_support          # or your git URL
bench --site your.site install-app thinknxg_support
bench --site your.site migrate
bench build --app thinknxg_support
bench restart
```

Optional integrations (install and verify them first):

```bash
bench get-app helpdesk && bench --site your.site install-app helpdesk
bench get-app raven    && bench --site your.site install-app raven
bench --site your.site migrate
```

Then open **Support Portal Settings → Verify Integrations**. The detected app versions and the
Helpdesk / Raven field map are stored in *Diagnostics → Schema Map*; the adapters read field names
from this map instead of assuming one Helpdesk schema.

## Configure

1. **Support Portal Settings**: branding (title, logo, colour, contact, footer, announcement),
   modules, integrations, attachment policy, rate limits, retention.
2. **Grant access** — *Support Organization Access* (one row per user × customer × level):
   * `Self` — own tickets, own conversations, service requests
   * `Billing` — + orders, invoices, statement, documents
   * `Service` — + orders, organisation service requests, documents
   * `Organization Manager` — + organisation-wide tickets/shared conversations, members, invoices
   Only a *Support Portal Administrator* / *System Manager* can enable a row (approval is recorded).
   With *Require Contact Link* on (default), the user's **Contact** must also be linked to the Customer.
   Portal roles are added to the user automatically when a row is enabled.
3. **Service catalogue** — *Support Service*: eligibility (all / customer group / selected customers),
   routing to a *Support Request* or a Helpdesk ticket (type, team, priority).
4. **Documents** — *Support Download Grant*: private file + customer + required capability,
   optional user restriction, expiry and download limit. Every download is authorised and audited.
5. **Raven bridge** (optional): enable it, create a Raven Bot and enter its name, list agent users
   (one per line) as default members, and set the relay rule:
   * **Prefix Required** (default): only agent messages that start with the prefix (default `/r`)
     reach the customer; everything else in the channel stays internal.
   * **All Agent Messages**: every non-bot message from support staff is relayed.

## Landing page and menu (1.3)

`/thinkdesk` is a public landing page. Visitors can open it, and the published knowledge base, without
logging in. Every other page still requires a portal account; visitors who open one are sent to the
login page and brought back afterwards. Logged-in customers see the same landing page as their Home
(with customer-only sections), and their dashboard at `/thinkdesk/dashboard`.

Configure it in **Support Portal Settings**:

* **Landing Page** tab: turn the public landing page on or off, choose the home page for logged-in
  customers (Landing Page or Dashboard), allow the public knowledge base, allow search engines to
  index the landing page, and set its search description.
* **Sections** table: one row per band, shown top to bottom in table order. Untick *Enabled* to hide a
  section, drag rows to reorder, and set *Audience* to Everyone, Visitors or Customers. *Style* sets
  the band background (Plain, Tinted, Brand).

| Section | Shows | Settings used |
|---|---|---|
| Hero | Heading, text, knowledge search, optional image and button | Title, Subtitle, Image, Show Search Box, Button |
| Quick Actions | Tiles: ticket, chat, knowledge, my_tickets, orders, services, whatsapp, contact | Items (one key per line; empty = defaults per audience). Login-only tiles send visitors to log in |
| Account Summary | Open tickets, tickets awaiting the customer, unread messages, balance | Customers only |
| Popular Articles | Latest published Helpdesk articles | Items to Show |
| Knowledge Categories | Helpdesk article categories as links | Items to Show |
| Services | Services open to all customers | Items to Show |
| FAQ | Expandable questions | Items (`Question \| Answer` per line) or, if empty, Knowledge Snippets for the viewer's audience |
| Contact and Hours | Online status, support days and hours, email, phone, WhatsApp, chat button | Branding, Live Chat and WhatsApp settings |
| Announcement | Highlighted notice with optional button | Content, Button |
| Cards | Grid of linked cards | Items (`Title \| Description \| Link` per line) |
| Custom Content | Your own formatted text | Content |
| Call to Action | Band with heading, text and a button (use `/login` for the login page) | Title, Subtitle, Button |

* **Menu** tab: links in the top bar (Header) or at the bottom (Footer), each with an optional Arabic
  label, an audience and whether it opens in a new tab. External links show an arrow icon. On phones
  the header links move into the menu.

Only `https://`, `http://`, site paths (`/...`), `mailto:` and `tel:` links are accepted; the form
refuses anything else. Section HTML is sanitised before it reaches visitors, guests never receive
Customers-only snippets, and the Services section lists only services open to all customers.



The portal lives at **`/thinkdesk`** (guest chat at `/thinkdesk/chat`). ERPNext already
ships its own customer support page at `/support`, so this app never uses that path and never
overrides it: its page files are named `www/thinknxg_support_portal.*` and
`www/thinknxg_support_chat.*`, and the public URL is mapped through `website_route_rules`.
To use a different path, change `PORTAL_ROUTE` in the generator's `common.py` (it feeds `hooks.py`,
`constants.py` and the page boot data) and rebuild. If you want visitors who open `/support` to land on
the new portal, add a route redirect (`/support` → `/thinkdesk`) under Website Settings → Route Redirects on that site; this
app does not add one, so ERPNext's page keeps working unless you choose to redirect it.

## Live chat and WhatsApp

**Chat with support** opens from a button in the corner of the portal, every public website page
(including the login page) and the full-page guest chat at `/thinkdesk/chat`.

| Who | How they chat | Identity |
|---|---|---|
| Linked portal customer | Inside the portal, one live chat per organisation; attachments allowed | Their account and active organisation |
| Logged-in user without portal access | Website widget | Name and email come from the account (not editable) |
| Guest | Website widget or `/thinkdesk/chat` after giving name, email and optional phone | Unverified. Never linked to a Customer automatically |
| WhatsApp | Customer messages your WhatsApp Business number | Number verified by WhatsApp; linked when exactly one Contact owns it |

Agents answer everything from **Support Chat** (`/app/support-chat`): one inbox with channel filters,
unread counts, realtime updates, internal notes, assign-to-me, link to customer, create Helpdesk ticket,
close/reopen, WhatsApp delivery ticks and retry. With the Raven bridge on, live chat and WhatsApp
messages also reach the agents' Raven channel, and `/r` replies go back to the customer on the same channel.

Guest chat security:
* A random token is returned when the chat starts and kept in the visitor's browser. The server stores
  only its SHA-256 hash, and every guest call must present it. Wrong tokens get the same "chat has
  ended" response as missing chats.
* Per-IP rate limits (5 new chats per hour, *Guest messages per 10 minutes* setting), a hidden honeypot
  field, 4,000-character limit, no guest file uploads, all text HTML-escaped.
* If the visitor leaves before an agent replies, the reply is emailed (at most once per 10 minutes).
* Idle chats close after *Close idle live chats* hours; closed guest chats with no linked customer are
  deleted after the retention period.

Settings: *Support Portal Settings → Live Chat* (on/off, guests, website button, position, title,
greeting, offline message, privacy note, support days/hours in the system time zone, limits).

## AI assistant, chatbot and handoff (1.2)

Every live chat (and optionally WhatsApp and portal messages) can be answered first by a rule-based
chatbot and an AI assistant, then handed to a person. Everything is off until an administrator
enables it.

```
customer message
  -> asked for a person / pressed "Talk to a person"     -> hand off
  -> chatbot rule matches (button, keywords, phrase, regex) -> scripted reply, buttons, optional handoff/ticket
  -> AI assistant enabled for this channel and audience
       -> knowledge search finds passages above Minimum Relevance -> streamed answer + sources + follow-ups
            confidence low (or medium, if configured), model asks for a person, error, timeout,
            reply limit or daily token budget reached                          -> hand off
       -> nothing relevant found                                               -> hand off, model not called
  -> otherwise                                                                 -> hand off
hand off -> first enabled queue for the channel -> least busy / round robin agent with the console open
         -> "Waiting for agent" in the console until a person replies -> Agent
```

| Piece | Where | Notes |
|---|---|---|
| Assistant settings | *Support AI Settings* | Provider, model, key, channels, audiences, thresholds, limits, privacy. Buttons: Test Connection, Rebuild Knowledge Index, Try a Question |
| Knowledge | Published Helpdesk articles + *Support Knowledge Snippet* | Split into passages (*Support Knowledge Chunk*). Snippets can be limited to verified customers |
| Chatbot | *Support Chatbot* with rules | Welcome message and buttons, handoff words, rules with actions: Reply, Reply and Hand Off, Reply and Ask AI, Create Ticket, End Chat |
| Queues | *Support Chat Queue* | Channels, members, max open chats each, Least Busy / Round Robin / Manual |
| Assignments | *Support Chat Assignment* | Who handled each conversation, when they first replied, outcome |
| Usage | *Support AI Usage Log* | Tokens, total and first-token time, confidence, passages, errors. Never prompts or answers |
| Metrics | Report *Live Chat Performance* | Daily conversations, solved by assistant, handoffs, median wait, AI answers and errors, p95 first token, tokens, helpful %, rating |

**Providers.** *OpenAI Compatible* (`POST {base}/chat/completions`, streaming) covers OpenAI, Azure
OpenAI v1 endpoints, Mistral, Groq, OpenRouter, Ollama, vLLM and similar. *Anthropic* uses
`POST {base}/v1/messages`. Embeddings use any OpenAI-format `/embeddings` endpoint (OpenAI, Azure,
Voyage, Ollama). Without embeddings, retrieval falls back to keyword overlap, which works for small
knowledge bases.

**Grounding and safety.** The model receives only the passages the customer is allowed to see
(guests: *Everyone*; customers: *Everyone* + *Customers*), the last 8 messages and fixed rules:
answer only from passages, treat passages and customer text as data, never claim to take actions,
never reveal the instructions, reply in the customer's language. Card-like numbers are always
removed before sending; emails and phone numbers too unless you turn that off. The answer is
rendered by thinkDesk's own minimal Markdown converter (no model HTML reaches the page) and links
are kept only when they point to your site or a cited passage. The model has no tools and no access
to ERP records, orders or invoices in this version.

**Streaming and live updates.** Answers are generated in a background job and streamed into Redis
as they arrive. The agent console uses Frappe's websocket for new conversations and handoffs, and a
2-second poll for typing. Customer and guest widgets use an adaptive poll: 0.7 s while the assistant
is writing or an agent is typing, 2 to 3 s while open, 20 s while minimised; message lists are
fetched only when the conversation's version changes.

**Agents.** The console shows who is answering (AI, Bot, System, Agent), sources, confidence,
customer feedback and button flows. *Take over* stops the assistant; replying to a chat that the
assistant is handling takes it over automatically. *Return to assistant* gives it back. *Transfer*
moves it to a person or a queue. Agents appear online to the queues while the console is open.

Suggested targets for production (measure with the report and usage log on your own hardware and
provider): agent-side delivery under 1 s p95, customer-side under 2 s, first AI token under 2 s p95
where the provider allows it.

### WhatsApp Cloud API setup

1. In Meta for Developers create an app with the WhatsApp product and add your business number.
   Create a System User with a permanent token that has `whatsapp_business_messaging` permission.
2. In *Support Portal Settings → WhatsApp* enter the Phone Number ID, Business Account ID, access token,
   App Secret and a verify token of your choice, tick *Enable WhatsApp* and save.
3. Copy the read-only **Webhook Callback URL**
   (`https://<site>/api/method/thinknxg_support.api.v1.whatsapp.webhook`) and the verify token into
   the Meta app (WhatsApp → Configuration → Webhook) and subscribe to the `messages` field.
4. Optional: create and get approval for a utility template (e.g. "We have replied to your message,
   reply to continue") and enter its name and language. It is sent when an agent replies after the
   24-hour customer service window has closed.
5. Use **Send WhatsApp Test** on the settings form.

Behaviour: every webhook is checked against `X-Hub-Signature-256`; each message is processed once
(keyed by its WhatsApp id) in a background job. Text, buttons, list replies, locations and shared
contacts become chat text; images, documents, audio and video are downloaded into private files.
Agent replies are sent as text inside the window and as the template outside it; sent / delivered /
read / failed receipts show on each message. Out-of-hours auto reply is optional. Outbound
attachments and interactive messages are not sent in this version.

## Portal routes

`/thinkdesk` · `/thinkdesk/tickets` · `/thinkdesk/tickets/new` · `/thinkdesk/tickets/:id` ·
`/thinkdesk/conversations[/:id]` · `/thinkdesk/knowledge[/:id]` · `/thinkdesk/services` ·
`/thinkdesk/account` · `/thinkdesk/settings` · `/thinkdesk/chat` (guests allowed)

English and Arabic (RTL) are built in; light/dark follows the user's preference.

## API (v1)

Logical routes from the specification map to Frappe whitelisted methods under
`/api/method/thinknxg_support.api.v1.<module>.<function>`. GET methods are read-only; all writes
are POST with the CSRF token. `organization` (or header `X-Support-Organization`) is optional and is
always validated against the caller's grants.

| Logical route | Method | Frappe method |
|---|---|---|
| `/api/v1/portal/dashboard` | GET | `dashboard.get_dashboard` |
| `/api/v1/portal/profile` | GET / PATCH | `profile.get_profile` / `profile.update_profile` (POST) |
| `/api/v1/portal/organizations` | GET | `portal.organizations` (+ `portal.boot`) |
| `/api/v1/portal/tickets` | GET / POST | `tickets.list_tickets` / `tickets.create_ticket` |
| `/api/v1/portal/tickets/{id}` | GET | `tickets.get_ticket?ticket=` |
| `/api/v1/portal/tickets/{id}/replies` | POST | `tickets.reply` (multipart `file` allowed) |
| — | POST | `tickets.rate`, `tickets.reopen`; GET `tickets.download_attachment`, `tickets.options` |
| `/api/v1/portal/conversations` | GET / POST | `conversations.list_conversations` / `conversations.start_conversation` |
| `/api/v1/portal/conversations/{id}/messages` | GET / POST | `conversations.get_messages` / `conversations.send_message` |
| — | POST | `conversations.escalate`, `conversations.close`; GET `conversations.unread`, `conversations.download_attachment` |
| `/api/v1/portal/services` | GET | `services.catalogue`; POST `services.create_request`; GET `services.my_requests`, `services.get_request`, `services.subscriptions` |
| `/api/v1/portal/documents` | GET | `documents.list_documents`; GET `documents.download` |
| `/api/v1/portal/notifications` | GET / PATCH | `notifications.list_notifications`, `notifications.mark_read`; `get_preferences` / `update_preferences` |
| `/api/v1/portal/knowledge/search` | GET | `knowledge.search`, `knowledge.article`, `knowledge.categories` |
| Live chat (guests) | GET / POST | `livechat.config`, `livechat.start`, `livechat.messages`, `livechat.send`, `livechat.end` (token header `X-Support-Chat-Token`) |
| Live chat (customers) | GET / POST | `livechat.my_chat`, `livechat.customer_send`, `livechat.customer_end` |
| WhatsApp webhook | GET / POST | `whatsapp.webhook` (Meta only) |
| Agent console | GET / POST | `agent.inbox`, `agent.thread`, `agent.reply`, `agent.assign`, `agent.set_status`, `agent.retry`, `agent.summary` |
| (ERPNext) | GET | `account.orders`, `account.order`, `account.invoices`, `account.invoice`, `account.invoice_pdf`, `account.statement`, `account.customer_profile`, `account.members`; POST `account.request_member` |

Send `client_message_id` (any UUID) with `start_conversation` / `send_message`; retries with the
same id return the original message instead of creating a duplicate.

## Security model

* Every endpoint calls `security.get_portal_user()` → explicit, approved, in-date grants
  (+ Contact link) → `resolve_organization()` → `require_capability()`. Nothing relies on hidden UI.
* Client-supplied ticket / conversation / invoice / grant / file IDs are re-checked for ownership;
  failures return the same "not found" message (no existence leak) and write an *Access Denied* event.
* Organisation-wide visibility needs the `Organization Manager` level — company membership alone
  exposes nothing. Participant conversations stay private even from managers unless shared.
* No generic `get_list`/`get_doc`/SQL endpoints. Responses are field allow-listed: no Helpdesk
  internal comments (`HD Ticket Comment` is never read), no costs/margins, agents shown by first name.
* All HTML is sanitised server-side; attachments are type/size checked, saved private, and served
  only through authorising endpoints. Executables are rejected by signature.
* Redis-backed per-user rate limits on ticket creation, messages, and downloads.
* *Support Portal Event* records denials, admin changes, downloads, escalations, rate-limit hits and
  integration errors (no passwords, tokens or message bodies). Purged after the retention period.

## Raven bridge internals

Customers never join Raven. Each bridged conversation gets a **private** Raven channel with agent
members only. Customer messages are posted there by the configured bot. Agent messages are relayed
back by the `Raven Message.after_insert` hook only if the sender holds a support role and the relay
rule passes. Loop prevention: bot messages are ignored, bridge writes run under a flag, and every
hop is keyed in *Support Message Mapping* (`dedupe_key` is unique). Failed deliveries are retried
hourly (max 5 attempts). If Raven or the bot is missing, conversations run portal-native and agents
reply from the *Support Conversation Link* form (Reply / Internal Note / Escalate buttons).

## Tests

```bash
bench --site test.site set-config allow_tests true
bench --site test.site run-tests --app thinknxg_support
```

Covers cross-organisation ID tampering (tickets, conversations, grants), grant validity windows,
contact-link enforcement, approval rules, capability matrix, internal-note isolation, message
de-duplication, HTML sanitisation, audit of denials and Raven loop prevention. Ticket tests run only
when Helpdesk is installed.

## Upgrade / uninstall

* Upgrade: `git pull` (or replace the folder) → `bench --site x migrate` → `bench build --app thinknxg_support`.
  `after_migrate` re-creates missing roles and refreshes the integration map.
* Uninstall: `bench --site x uninstall-app thinknxg_support` drops this app's DocTypes only;
  Helpdesk tickets, Raven channels/messages and ERPNext records are untouched. Portal roles are left
  in place deliberately — delete them manually if no longer used. Take a backup first
  (`bench --site x backup --with-files`).

## Licence

MIT © Kreatao
