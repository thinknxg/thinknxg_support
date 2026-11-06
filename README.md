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

## Knowledge base and help-article importer (1.4)

The portal, landing page and AI assistant read **one knowledge base**: published Helpdesk articles
(when Helpdesk is installed) plus thinkDesk's own *Support Knowledge Article* records (which work
without Helpdesk). Articles marked *Customers* are shown only to signed-in portal customers; visitors
see *Everyone* articles when **Public Knowledge Base** is on in Support Portal Settings.

### Reading articles (1.5)

* **Sidebar**: every category with its article titles, like a wiki. The open article is highlighted and its
  category expanded; a filter box narrows titles. On phones it folds into a *Browse articles* button.
  Built-in articles follow **Sort Order** within each category, then title; categories follow their Sort Order.
* **Copy link**: copies the article's address (`/thinkdesk/knowledge/<id>`) for sharing. Visitors can open
  it when the knowledge base is public; otherwise the reader is asked to log in.
* **Was this article helpful?** Thumbs up or down, changeable, one vote per signed-in user or per visitor
  (an anonymous key from address and browser). *No* asks what was missing (optional). Votes are kept in
  *Support Article Feedback* and totalled on built-in articles (*Helpful Votes*, *Not Helpful Votes*).
  Limited to 20 votes per reader per 10 minutes.
* **If your issue isn't resolved, raise a support ticket here**: opens a new ticket with the article title as
  subject and its link in the description. Visitors are sent to log in first. *Chat with us* appears when live
  chat is on.
* **Related articles**: up to five, from the same category first, then articles whose titles share words.
  Only articles the reader may see are listed.

### Importing and rebranding articles

1. Open **Support Knowledge Source → Frappe Help Centre** (created disabled on install).
2. **Access**: a Helpdesk site answers visitors with *HTTP 403 "Please sign in to read the knowledge
   base"* unless its own *Public Knowledge Base* setting is on, and support.frappe.io has it off. Choose:
   * *Login*: username and password of an account on that site (not for single sign-on accounts);
   * *Browser Session*: sign in to the site in your browser, open developer tools → Application →
     Cookies, copy the `sid` value and paste it (it stops working when that browser session ends);
   * *API Key*: if the site's administrator gives you one. **Test Connection** shows the
   first three titles, rebranded, with the original in brackets.
3. **Rebranding** rules come filled in, longest phrase first:

   | Find | Replace with |
   |---|---|
   | Frappe Framework | thinkNXG Framework |
   | Frappe Cloud | thinkNXG Cloud |
   | Frappe HR | thinkNXG HR |
   | ERPNext | thinkNXG ERP |
   | Frappe | thinkNXG |

   Only readable text changes (titles, paragraphs, headings, image descriptions, category names).
   Code blocks, commands, URLs, e-mail addresses, file paths and API names such as `frappe.get_doc`
   stay exactly as they are, so instructions still work.
4. **Website and E-mail Rebranding** moves links, web addresses and e-mail addresses in the articles to
   thinkNXG's own sites. One rule is on by default: `docs.frappe.io/erpnext` → `https://docs.thinknxg.com/thinknxgerp`,
   keeping the rest of the path. Rows for frappe.io, frappe.cloud, erpnext.com, frappehr.com, the other docs.frappe.io
   sections, discuss.frappe.io, school.frappe.io and Frappe e-mail domains are listed but off: fill in the
   thinkNXG address and tick **Enabled**. Code, image sources, links to the import source and the attribution
   footer are never changed. After changing rules, **Re-apply Rebrand Rules** updates proposals and
   **Apply Link Rules to Published Articles** updates what is already live.
5. **Publish To**: *Automatic* uses Helpdesk when it is installed, otherwise the built-in knowledge base.
   Pick the audience, whether to copy images into this site, and how to treat links to the source site
   (point them to the imported copy, keep them, or remove the link and keep the text).
6. **Import Now**. It runs in the background and creates one *Support Article Import* proposal per
   article. **Nothing is published yet.**
7. Review in **Support Article Import**. Each proposal shows the original and the rebranded version
   side by side, the number of names replaced, and *Check before publishing* notes. Proposals with
   notes are set to *Needs Review*: for example Frappe's own websites or e-mail addresses, prices
   or plans, or Frappe Cloud hosting steps that may differ on thinkNXG Cloud. Edit the proposed text
   if needed, then **Approve and Publish**. You can also select many in the list and use
   **Actions → Approve and Publish**.
8. Published articles appear in `/thinkdesk/knowledge`, in the landing page's *Popular Articles* and
   *Knowledge Categories* sections, and in the AI assistant's answers (indexed automatically).

Re-running the import is safe. Unchanged articles are skipped. If a published article changed at the
source, its proposal becomes *Source Changed* and the published copy is **not** overwritten until you
approve the update. **Re-apply Rebrand Rules** refreshes unpublished proposals after you edit the rules.
The source can also be a list of page URLs (Markdown `.md` or HTML), one per line, optionally
`Category | URL`.

### Licence and attribution — read before publishing

* Frappe's legal page says its **documentation** is licensed CC BY-SA, while its **website content and
  marketing material** are reserved and may not be copied or used commercially without permission.
  It also reserves Frappe's trademarks. The help articles at support.frappe.io are not clearly placed
  in either group. **Get written confirmation from Frappe** before you publish them, or import from
  the documentation instead (docs.frappe.io, for example `https://docs.frappe.io/erpnext/<page>.md`, using a
  *Page URLs* source).
* Publishing is blocked until **I Have Checked the Source's Licence** is ticked on the source. Ticking it
  is recorded in the audit log.
* Every published article ends with an attribution: the original title and link, the copyright owner,
  the licence and its link, and a note that names were changed. The attribution must contain the
  source link, owner and licence. CC BY-SA also requires that you share the adapted articles under
  the same licence.
* Rebranding changes product names in the text, not the facts. The *Check before publishing* notes
  exist because hosting steps, prices, support contacts and partner programmes described for Frappe
  may not be true for thinkNXG.

## Customer feedback after chats (1.8)

When a chat closes (the agent ends it, the customer ends it, or it closes for inactivity), the customer is asked:

1. **How would you rate the agent?** 1 to 5 stars: Excellent, Good, Average, Poor, Very Poor
2. **Was your issue resolved?** Yes / Partially / No
3. **Additional comments**

* **Where it is asked**: in the chat widget right after the chat closes (visitors and signed-in customers), and on
  WhatsApp as a link to a feedback page (`/thinkdesk/feedback`, valid 3 days, one chat per link).
* **Settings** (Support Portal Settings → Live Chat → *Customer Feedback Survey*): *Ask for Feedback* = Off,
  Optional (customers can skip) or **Required** (no skip; the widget keeps asking for up to a day before a new chat
  can start); title and intro; whether to ask about resolution and for comments; comments required at or below N
  stars; the WhatsApp message; what counts as negative (default 2 stars or fewer) and who is alerted (default
  *Support Manager*, plus e-mail).
* **Support Chat Feedback** records each answer, linked to the chat ID, the agent who handled it (or *Assistant only*),
  the queue and the customer, with sentiment (Positive 4–5 ★, Neutral, Negative). Supervisors see all feedback and
  comments; agents see feedback about their own chats.
* **Alerts**: negative feedback alerts supervisors (pop-up, sound, e-mail); positive feedback thanks the agent.
  Both are alert-centre activities with their own sounds.
* **Reports**: **Agent CSAT** by agent, or by agent and week or month: chats, surveys, average rating, CSAT % (share
  of 4–5 ★), resolved / partially / not resolved, negative count. Number cards on the Support Query Management
  workspace: average rating and feedback count (30 days), negative feedback (7 days) and negative feedback to review.

## Agent alerts, canned responses and chat wrap-up (1.7)

### Alert centre

Every desk page carries one alert centre. Each activity has its own pop-up colour and sound:

| Activity | Who is alerted | Default sound | Repeats | Stops when |
|---|---|---|---|---|
| New Chat | The assigned agent, else the chat queue's members, else all agents | Ring | Every 10 s until acknowledged | Acknowledged, the chat is assigned (others stop), answered or closed |
| Chat Message | The assigned agent, else the queue's members | Ping | Once | Answered |
| New Ticket | The ticket's assignees, else its Helpdesk team, else all agents | Chime | Every 60 s, 3 times | Acknowledged, assigned, replied to or moved on from Open |
| Ticket Assigned | The new assignee | Bell | Every 30 s, 5 times | Acknowledged or replied to |
| Conversation Message | The assigned agent, else all agents | Pop | Once | Answered |
| Escalation | As set in Support Escalation Settings | Siren (distinct, loudest) | Every 15 s until acknowledged | Acknowledged, or the escalation moves to In Progress / Resolved / Closed |

* **Support Alert Settings** (team defaults): per activity, on/off, pop-up, sound (Chime, Bell, Ping, Pop, Ring,
  Double Beep, Knock, Siren, Alarm or an uploaded MP3/OGG/WAV), volume, repeat until acknowledged, interval, maximum
  repeats and system notifications; which roles count as agents; how long alerts keep sounding (default 24 h).
* **My Alert Preferences** (each agent): mute all, overall volume, system notifications, and per activity their own
  sound, pop-up and repeat choice, with **Test Sound** buttons. The ⚙ on any alert opens it.
* **Works on any screen**: alerts appear on every desk page. Only one browser tab plays sounds, so several open tabs
  don't ring together. Repeats are timed by the browser's audio clock, so they keep ringing in a background tab.
  With the tab in the background, a system notification appears too (allow it once in My Alert Preferences).
  Browsers need one click on the page before they play sound; a button asks for it. Each tab unlocks itself on the
  first click or key press, only a tab with sound allowed rings, and the tab you are working in takes over. If live
  updates (socket.io) are down, alerts still arrive within 15 seconds.
* **Check Alerts** (My Alert Preferences) shows what stands between this browser and a sound (agent role, team
  rules, mute, live updates, sound allowed, ringing tab, system notifications) and sends a real test alert.
* **Acknowledgement tracking**: every alert that needs acknowledging is kept in *Support Agent Alert* with how
  long it took. The **Agent Alert Response** report shows, per agent and activity, alerts, acknowledged, picked up
  (assigned or answered first), missed, and average / median / longest seconds to acknowledge.
* The Helpdesk app's own agent screens (`/helpdesk`) do not load desk scripts: keep one desk tab open (any `/app`
  page) to hear ticket alerts.

### Canned responses

**Support Canned Response**: title, optional `/shortcut`, category, channel, language, visibility (Team or Only Me)
and the message, with placeholders `{customer_name}` `{customer_first_name}` `{agent_name}` `{agent_first_name}`
`{company}` `{ticket}` `{conversation}`. In the Support Chat console, type `/` in the reply box for matching
responses (arrows and Enter or Tab), or click **Canned responses** to search and filter by category. The text lands
in the reply box with placeholders filled, ready to edit before sending. Agents create their own; they edit and
delete only their own; managers manage all. Helpdesk canned responses are listed too when Helpdesk is installed.
Usage is counted so the most-used come first.

### Ending a chat

**Close** in the console opens **End chat**: the reason (list in Support Portal Settings → Live Chat → *Ending a
Chat*, required by default), the wrap-up questions (Yes/No, choice, text or rating, optionally required) and notes
for the team. They are saved on the conversation (*Chat Wrap-up* section, filterable by reason) and added to its
history as an internal note; the customer only gets the optional closing message. An open escalation for the chat
gets the reason as a note.

## Escalations and Support Query Management (1.6)

Every escalated customer query gets one **Support Escalation** record, an alert for the team, and a place in the
**Support Query Management** workspace (`/app/support-query-management`).

### What counts as an escalation

| Section | Raised when | Escalation type |
|---|---|---|
| Support Chat | The assistant hands a live chat or WhatsApp chat to a person (low confidence, no answer, limits, a chatbot rule) | AI Handoff · Chatbot Rule |
| Support Chat | The customer asks for a person | Customer Asked for Agent |
| Support Chat | A chat starts with people because the assistant is off for it | Direct Live Chat |
| Conversation | A portal conversation is escalated (by the customer or an agent) | Conversation Escalated |
| Support Ticket | A service request is escalated to a ticket | Request Escalated |
| Support Ticket | A Helpdesk ticket gets an escalation priority (default *Urgent*) | Urgent Ticket |
| Support Ticket | A Helpdesk ticket misses its SLA | SLA Breach |
| Any | An agent clicks **Escalate to Team** on a chat, conversation, ticket or service request | Manual |

Each switch is in **Support Escalation Settings**. A query is escalated once; a later trigger of a different kind
(for example an SLA breach on an urgent ticket) raises the **escalation level** instead of creating a second record.

### Notifications

Each alert carries the escalation and source reference, customer name and contact details, the escalation type,
subject and description, date and time, the assigned person and team, the priority, and a direct link.

| Channel | What happens | Setting |
|---|---|---|
| In-app | A pop-up card with a sound in any desk page, until opened or acknowledged; missed alerts appear at the next sign-in | In-App Alert, Play a Sound |
| Notification center | An entry under the bell icon | Notification Center |
| Email | A formatted email to recipients and extra team mailboxes | Email, Extra Email Addresses |
| WhatsApp | A message to listed numbers through the WhatsApp channel | WhatsApp, Phone Numbers, Template |

Recipients: the assigned person, the team's members, the listed roles (default *Support Manager*) and users. Overdue
alerts go to the assigned person and the *Also Alert Roles*. WhatsApp messages that start a conversation need an
approved template with six body variables: {{1}} reference, {{2}} customer, {{3}} type, {{4}} subject, {{5}} priority,
{{6}} link. Without one, a plain message is sent, which WhatsApp delivers only within 24 hours of that person's last
message to your business number.

### Working an escalation

* **Statuses**: New (not yet assigned) → Pending (assigned, no reply yet) → In Progress (someone replied) →
  Resolved → Closed. A customer writing again reopens a resolved escalation.
* **Priority**: Critical, High, Medium, Low, with first-response and resolution targets per priority
  (defaults 15 min / 4 h, 30 min / 8 h, 2 h / 24 h, 8 h / 72 h). Due times and **Overdue** are checked every 5 minutes.
* **Assignment**: chats follow their chat queue's rule; conversations and tickets go to the least busy member of the
  default team. **Assign to Me**, **Reassign** and **Escalate Further** (raise level, priority and owner, with a
  reason) are on the form. Reassigning a chat escalation also hands the chat itself to that person.
* **Automatic tracking**: the first customer-visible reply sets *First Response* and moves it to In Progress; a
  customer message sets *Customer Waiting*; closing the chat or resolving the ticket or request resolves it. A chat
  that ends before anyone replied stays open so the team follows up.
* **History and notes**: every change is in *Escalation History*; **Add Internal Note** keeps team-only notes.
  The *Activity* tab shows the messages on the query and the customer's other escalations, tickets and requests.
* **Search, filters, sorting**: the list opens on open escalations, with overdue in red and priority colours;
  filter by section, status, priority, assignee, team, customer or overdue.

### The workspace

Six indicators (New Escalations, Unassigned, Pending Response, In Progress, Overdue, Resolved in the last 7 days),
escalations per day and open escalations by section and priority, then one block each for **Support Chat**,
**Conversation** and **Support Tickets** with open / unassigned / pending-response / overdue counts and a live list.

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
| Knowledge | Published Helpdesk articles + built-in *Support Knowledge Article* + *Support Knowledge Snippet* | Split into passages (*Support Knowledge Chunk*). Snippets can be limited to verified customers |
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
| `/api/v1/portal/knowledge/search` | GET (+ POST feedback) | `knowledge.search`, `knowledge.article`, `knowledge.categories`, `knowledge.sidebar`, `knowledge.related`, `knowledge.feedback` |
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
de-duplication, HTML sanitisation, audit of denials and Raven loop prevention, the rebrand engine (code,
URLs and paths untouched), the importer against a faked source (proposals only, licence gate,
attribution, source changes not overwriting) and knowledge visibility for visitors and customers.
Ticket tests run only when Helpdesk is installed.

## Upgrade / uninstall

* Upgrade: `git pull` (or replace the folder) → `bench --site x migrate` → `bench build --app thinknxg_support`.
  `after_migrate` re-creates missing roles and refreshes the integration map.
* Uninstall: `bench --site x uninstall-app thinknxg_support` drops this app's DocTypes only;
  Helpdesk tickets, Raven channels/messages and ERPNext records are untouched. Portal roles are left
  in place deliberately — delete them manually if no longer used. Take a backup first
  (`bench --site x backup --with-files`).

## Licence

MIT © Kreatao
