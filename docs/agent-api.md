# thinkNXG Support staff API v1 (Agent apps)

Base: `https://<site>/api/method/thinknxg_support.api.staff.v1.<method>` · JSON in, `{"message": …}` out ·
`Authorization: Bearer <access token>` on every call except `auth_config`.

The web console (`/app/support-chat`), the Windows app and the mobile apps read and write the **same records**
(Support Conversation Link, Support Portal Message, HD Ticket, Communication, Comment, Support Agent Alert).

## Access rules (every call)

1. **Signed in** with an OAuth token issued to the agent's own Frappe user (no shared or service accounts).
2. **Staff**: enabled *System User* with a staff role (Support Agent, Support Manager, Support Portal Administrator,
   System Manager, or the roles in *Support Alert Settings* such as Helpdesk's Agent / Agent Manager). Website users
   and customers get **403** even with a valid token. *Support Agent App Settings → Allow the Agent Apps* off → 403.
3. **Record access**, the same for lists and direct lookups (including links opened from alerts and notifications):
   * Conversations: DocType permission, then queue visibility: managers see all; agents see conversations in queues
     they are an active member of, conversations assigned to them, and conversations in no queue.
   * Tickets: Helpdesk's own permission hooks (`frappe.get_list` as the agent for lists, `doc.check_permission`
     for lookups), so team restrictions apply unchanged.
4. Customer-visible replies and internal notes are separate records/flags in storage (`is_internal` on Support
   Portal Message; Communication vs Comment on tickets) and in delivery: notes never reach the portal, the widget,
   WhatsApp or email.

## Errors

| HTTP | Meaning | Extra fields |
|---|---|---|
| 401 | Not signed in / token expired → refresh once, then ask the agent to sign in | |
| 403 | Not a staff account, or no access to this record | `_server_messages` |
| 404 | Record not found | |
| 409 | **Conflict**: someone else changed it first (claim, transfer, close, ticket update / assign) | `error_code: "conflict"`, `error_message`, `conflict` (record as it is now) |
| 417 | Validation (Frappe `ValidationError`) | `_server_messages` |
| 422 | **Action required** | `error_code` (`whatsapp_window_closed`, `conversation_closed`, `helpdesk_unavailable`), `error_message`, `actions` |
| 429 | Rate limited | |

## Pagination

Lists return `{"items": [...], "next_cursor": "<opaque>" | null}`. Cursors encode the sort key and name of the last
row (`(last_activity_at, name)` for conversations, `(modified, name)` for tickets), so pages never repeat or skip
rows when new activity arrives. `limit` ≤ 50 (messages ≤ 100).

## Idempotency

`reply`, `ticket_reply` and `ticket_note` require `client_request_id` (a UUID made by the app per draft). A retry
with the same id returns the first result with `"duplicate": true` and never sends twice. Conversations: unique
index on (conversation, client_message_id). Tickets: *Support Agent Request* log with a unique request id.

## Methods

| Method | Verb | Parameters | Returns |
|---|---|---|---|
| `auth_config` | GET (guest) | | `enabled, api_version, site_name, client_id, scopes, redirect_uris, authorize_url, token_url, revoke_url, userinfo_url` |
| `bootstrap` | GET | | `api_version, server_time, site{url,name,app_version}, agent{user,full_name,email,image,is_manager,helpdesk_agent}, capabilities{conversations,live_chat,whatsapp,raven,helpdesk,assistant,wrap_up,canned_responses,alerts,push,realtime,integrations}, queues[{name,member}], poll{inbox_seconds,thread_seconds,alerts_seconds}` |
| `conversations` | GET | `view` all\|mine\|unassigned\|waiting, `channel` Portal\|Live Chat\|WhatsApp, `status` open\|closed\|all, `queue`, `q`, `cursor`, `limit` | page of ConversationSummary |
| `conversation` | GET | `name` | ConversationDetail (summary + `contact`, `customer_name`, `created_at`, `handoff_reason`, `actions{claim,transfer,reply,note,close,take_over,return_to_assistant,whatsapp_window_open}`, `read_up_to`) |
| `messages` | GET | `name`, `before` \| `after` cursor, `limit` | `items` (oldest first), `before_cursor`, `has_more_before`, `latest_cursor` |
| `mark_read` | POST | `name`, `message` | `read_up_to` — per agent, only moves forward |
| `claim` | POST | `name` | ConversationDetail · 409 if another agent has it (row lock: one winner) |
| `transfer` | POST | `name`, `user` \| `queue`, `expected_assignee` | ConversationDetail · 409 if the owner changed |
| `take_over` / `return_to_assistant` | POST | `name` | ConversationDetail |
| `closing_form` | GET | | `reasons, require_reason, questions[{idx,question,answer_type,required,options}], closing_message` |
| `close` | POST | `name`, `reason`, `notes`, `answers{idx: answer}`, `send_closing_message`, `expected_status` | ConversationDetail (wrap-up saved, as in the web console) |
| `canned_responses` | GET | `channel` | canned responses the agent may use |
| `reply` | POST | `name`, `text`, `client_request_id`, `internal` 0\|1 | `{message, duplicate}` · 422 `whatsapp_window_closed` |
| `tickets` | GET | `view` mine\|unassigned\|all, `status` open\|closed\|<status>, `priority`, `q`, `cursor`, `limit` | page of Ticket |
| `ticket` | GET | `name` | Ticket + `description, linked_conversation, can_write, statuses[{name,label,category,color}], priorities` (marks it seen) |
| `ticket_timeline` | GET | `name`, `cursor`, `limit` | `items[{id, kind email\|note, internal, direction, author, author_email, html, to, cc, delivery, created_at}]` |
| `ticket_reply` | POST | `name`, `text`, `client_request_id` | `{id, kind, duplicate}` — Helpdesk `reply_via_agent` (email to the ticket's contact) |
| `ticket_note` | POST | `name`, `text`, `client_request_id` | `{id, kind, duplicate}` — Helpdesk `new_comment` (staff only) |
| `ticket_update` | POST | `name`, `status`, `priority`, `team`, `expected_modified` | Ticket · 409 if changed since `expected_modified` |
| `ticket_assign` | POST | `name`, `agent` (default: me), `expected_assignees` | Ticket · 409 if the owners changed |
| `alerts` | GET | | `items` (open alerts for this agent) |
| `acknowledge_alerts` | POST | `ids` | `acknowledged` (clears them in every tab and device) |
| `open_target` | GET | `doctype`, `name` | `{kind: conversation\|ticket\|web, id\|url}` after checking access again |
| `register_device` | POST | `push_token`, `platform` Android\|iOS\|Windows, `device_name`, `app_version` | `{device}` |
| `sign_out` | POST | `push_token` | stops push to this device (the app then revokes its token and clears local data) |

**ConversationSummary**: `id, subject, display_name, channel, status, handling, queue, assignee{user,name}, customer,
is_guest, ticket, last_activity_at, unread (this agent), preview, whatsapp_window_open, version`.

**Ticket**: `id, subject, status, status_category, priority, raised_by, customer, contact, team,
assignees[{user,name}], sla{response_by, resolution_by, status, first_responded_on}, created_at, modified, unread`.

## Sign-in (OAuth 2, authorization code + PKCE)

* Frappe's own provider: `/api/method/frappe.integrations.oauth2.authorize | get_token | revoke_token`.
* Public client (`token_endpoint_auth_method = None`), PKCE S256, `scope = all openid`, allowed roles = staff roles.
  Created by *Support Agent App Settings → Create OAuth Client*; the app reads the client id from `auth_config`.
* Redirects: Windows `http://127.0.0.1:43823/callback` (loopback, RFC 8252); Android / iOS
  `com.thinknxg.agent://oauth2redirect` (Custom Tabs / ASWebAuthenticationSession).
* Tokens are stored only in the OS secure store (Keystore, Keychain, Windows Credential Manager). Refresh with
  `grant_type=refresh_token`; sign-out calls `sign_out`, revokes both tokens and clears the store.

## Updates

First release: authenticated polling (inbox 10 s, open conversation 4 s, alerts 15 s; set in *Support Agent App
Settings*), plus a refresh on reconnect and on resume. Realtime (Socket.IO) follows once per-room event
authorization for bearer-token clients is verified. Push (next increment): FCM (Android, and iOS through APNs in
Firebase) with generic lock-screen text ("New support activity"); opening a push calls `open_target` after sign-in.

## Roadmap

* Increment 2 — full workspace: canned responses picker, attachments (authorised download per file), transfer
  picker with agents and queues, customer history, ticket team change, typing indicators.
* Increment 3 — packaging: alert sounds, push notifications, Windows installer (MSIX / Inno Setup, signed),
  Android App Bundle and iOS TestFlight builds (macOS runner), auto-update channel.
