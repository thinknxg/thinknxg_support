// Portal strings (English / Arabic). Keys are dotted paths.
export const messages = {
	en: {
		nav: {
			dashboard: "Dashboard", tickets: "Tickets", conversations: "Messages", knowledge: "Knowledge base",
			services: "Services", account: "Orders & invoices", settings: "Settings", logout: "Log out",
			agent: "Agent workspace", notifications: "Notifications", organization: "Organization",
		},
		common: {
			loading: "Loading…", retry: "Try again", save: "Save", saved: "Saved", cancel: "Cancel", send: "Send",
			submit: "Submit", search: "Search", back: "Back", attach: "Attach files", none: "Nothing here yet",
			view_all: "View all", download: "Download", close: "Close", markAllRead: "Mark all read",
			yes: "Yes", no: "No", optional: "optional", of: "of", total: "Total", status: "Status", date: "Date",
		},
		errors: {
			network: "Can't reach the server. Check your connection and try again.",
			forbidden: "You don't have access to this.", generic: "Something went wrong. Please try again.",
			unlinked: "Your account isn't linked to an organization yet",
			unlinked_help: "Ask your company administrator or our support team to grant you portal access.",
			not_found: "Page not found",
		},
		dash: {
			welcome: "Welcome back", open: "Open", waiting: "Awaiting you", resolved: "Resolved", overdue: "Overdue",
			unread: "Unread messages", outstanding: "Outstanding balance", recent_tickets: "Recent tickets",
			recent_messages: "Recent conversations", articles: "Helpful articles", quick: "Quick actions",
			new_ticket: "Raise a ticket", new_message: "Message support", browse_services: "Request a service",
			requests: "Your service requests",
		},
		tickets: {
			title: "Support tickets", new: "New ticket", mine: "My tickets", org: "Organization",
			all: "All", open: "Open", waiting: "Awaiting you", resolved: "Resolved", subject: "Subject",
			description: "Describe the issue", type: "Category", priority: "Priority", create: "Submit ticket",
			suggested: "These articles may answer your question", reply: "Write a reply…", send_reply: "Send reply",
			timeline: "Conversation", sla_response: "First response by", sla_resolution: "Resolution by",
			team: "Team", reopen: "Reopen ticket", rate: "Rate this resolution", rate_comment: "Anything to add?",
			thanks: "Thanks for your feedback", created: "Ticket created", attachments: "Attachments",
			unavailable: "Ticketing is temporarily unavailable.", you: "You", overdue: "Overdue",
			search_ph: "Search by subject or number",
		},
		conv: {
			title: "Messages", new: "New conversation", subject: "Topic", message: "Message", start: "Start conversation",
			type_message: "Type a message…", escalate: "Convert to ticket", escalated: "Linked to ticket",
			share_org: "Visible to my organization's managers", closed: "This conversation is closed.",
			close: "Close conversation", empty: "Select a conversation", provider_raven: "Connected to the support team",
		},
		kb: { title: "Knowledge base", search: "Search articles", categories: "Categories", all: "All articles",
			not_helpful: "Still need help?", raise: "Raise a ticket" },
		services: {
			title: "Services", catalogue: "Service catalogue", request: "Request", my_requests: "My requests",
			subscriptions: "Subscriptions & licences", details: "Details", related: "Related document",
			priority: "Priority", submitted: "Request submitted", response: "Response from support",
			plans: "Plans", ends: "Ends",
		},
		account: {
			title: "Orders & invoices", orders: "Orders", invoices: "Invoices", statement: "Statement",
			documents: "Documents", outstanding: "Outstanding", overdue: "Overdue", due: "Due",
			delivered: "Delivered", billed: "Billed", pdf: "Download PDF", query: "Ask about this",
			payments: "Recent payments", items: "Items", qty: "Qty", rate: "Rate", amount: "Amount", tax: "Tax",
			only_outstanding: "Outstanding only", remaining: "downloads left",
		},
		settings: {
			title: "Settings", profile: "Profile", language: "Language", timezone: "Time zone",
			default_org: "Default organization", theme: "Appearance", notifications: "Notifications",
			email_ticket_updates: "Email me when a ticket status changes",
			portal_ticket_updates: "Show ticket and request updates in the portal",
			email_message_alerts: "Email me when support replies to a message",
			portal_message_alerts: "Show message alerts in the portal",
			email_request_updates: "Email me about service request updates",
			email_invoice_alerts: "Email me about new invoices",
			members: "Organization members", request_member: "Request access for a colleague",
			member_email: "Email", member_name: "Full name", member_level: "Access level",
			member_requested: "Request sent to the administrator",
		},
		admin: { warnings: "Administrator notices", settings: "Open portal settings" },
	},
	ar: {
		nav: {
			dashboard: "لوحة التحكم", tickets: "التذاكر", conversations: "الرسائل", knowledge: "قاعدة المعرفة",
			services: "الخدمات", account: "الطلبات والفواتير", settings: "الإعدادات", logout: "تسجيل الخروج",
			agent: "مساحة عمل الوكيل", notifications: "الإشعارات", organization: "الجهة",
		},
		common: {
			loading: "جارٍ التحميل…", retry: "إعادة المحاولة", save: "حفظ", saved: "تم الحفظ", cancel: "إلغاء",
			send: "إرسال", submit: "إرسال", search: "بحث", back: "رجوع", attach: "إرفاق ملفات", none: "لا يوجد شيء بعد",
			view_all: "عرض الكل", download: "تنزيل", close: "إغلاق", markAllRead: "تعليم الكل كمقروء",
			yes: "نعم", no: "لا", optional: "اختياري", of: "من", total: "الإجمالي", status: "الحالة", date: "التاريخ",
		},
		errors: {
			network: "تعذر الاتصال بالخادم. تحقق من الاتصال وحاول مرة أخرى.", forbidden: "ليست لديك صلاحية الوصول.",
			generic: "حدث خطأ ما. يرجى المحاولة مرة أخرى.", unlinked: "حسابك غير مرتبط بأي جهة بعد",
			unlinked_help: "اطلب من مسؤول شركتك أو فريق الدعم منحك صلاحية الدخول إلى البوابة.",
			not_found: "الصفحة غير موجودة",
		},
		dash: {
			welcome: "مرحباً بعودتك", open: "مفتوحة", waiting: "بانتظار ردك", resolved: "محلولة", overdue: "متأخرة",
			unread: "رسائل غير مقروءة", outstanding: "الرصيد المستحق", recent_tickets: "أحدث التذاكر",
			recent_messages: "أحدث المحادثات", articles: "مقالات مفيدة", quick: "إجراءات سريعة",
			new_ticket: "فتح تذكرة", new_message: "مراسلة الدعم", browse_services: "طلب خدمة", requests: "طلبات الخدمة",
		},
		tickets: {
			title: "تذاكر الدعم", new: "تذكرة جديدة", mine: "تذاكري", org: "الجهة", all: "الكل", open: "مفتوحة",
			waiting: "بانتظار ردك", resolved: "محلولة", subject: "الموضوع", description: "صف المشكلة",
			type: "الفئة", priority: "الأولوية", create: "إرسال التذكرة", suggested: "قد تجيب هذه المقالات عن سؤالك",
			reply: "اكتب رداً…", send_reply: "إرسال الرد", timeline: "المحادثة", sla_response: "الرد الأول قبل",
			sla_resolution: "الحل قبل", team: "الفريق", reopen: "إعادة فتح التذكرة", rate: "قيّم الحل",
			rate_comment: "هل لديك ما تضيفه؟", thanks: "شكراً على ملاحظاتك", created: "تم إنشاء التذكرة",
			attachments: "المرفقات", unavailable: "نظام التذاكر غير متاح مؤقتاً.", you: "أنت", overdue: "متأخرة",
			search_ph: "ابحث بالموضوع أو الرقم",
		},
		conv: {
			title: "الرسائل", new: "محادثة جديدة", subject: "الموضوع", message: "الرسالة", start: "بدء المحادثة",
			type_message: "اكتب رسالة…", escalate: "تحويل إلى تذكرة", escalated: "مرتبطة بالتذكرة",
			share_org: "مرئية لمديري جهتي", closed: "هذه المحادثة مغلقة.", close: "إغلاق المحادثة",
			empty: "اختر محادثة", provider_raven: "متصلة بفريق الدعم",
		},
		kb: { title: "قاعدة المعرفة", search: "ابحث في المقالات", categories: "التصنيفات", all: "كل المقالات",
			not_helpful: "هل ما زلت بحاجة إلى مساعدة؟", raise: "فتح تذكرة" },
		services: {
			title: "الخدمات", catalogue: "دليل الخدمات", request: "طلب", my_requests: "طلباتي",
			subscriptions: "الاشتراكات والتراخيص", details: "التفاصيل", related: "مستند مرتبط", priority: "الأولوية",
			submitted: "تم إرسال الطلب", response: "رد فريق الدعم", plans: "الخطط", ends: "ينتهي",
		},
		account: {
			title: "الطلبات والفواتير", orders: "الطلبات", invoices: "الفواتير", statement: "كشف الحساب",
			documents: "المستندات", outstanding: "المستحق", overdue: "متأخر", due: "تاريخ الاستحقاق",
			delivered: "تم التسليم", billed: "تمت الفوترة", pdf: "تنزيل PDF", query: "استفسار بخصوص هذا",
			payments: "آخر المدفوعات", items: "الأصناف", qty: "الكمية", rate: "السعر", amount: "المبلغ", tax: "الضريبة",
			only_outstanding: "المستحقة فقط", remaining: "تنزيلات متبقية",
		},
		settings: {
			title: "الإعدادات", profile: "الملف الشخصي", language: "اللغة", timezone: "المنطقة الزمنية",
			default_org: "الجهة الافتراضية", theme: "المظهر", notifications: "الإشعارات",
			email_ticket_updates: "راسلني عند تغيّر حالة التذكرة",
			portal_ticket_updates: "اعرض تحديثات التذاكر والطلبات في البوابة",
			email_message_alerts: "راسلني عند رد الدعم على رسالة",
			portal_message_alerts: "اعرض تنبيهات الرسائل في البوابة",
			email_request_updates: "راسلني بتحديثات طلبات الخدمة",
			email_invoice_alerts: "راسلني عند صدور فواتير جديدة",
			members: "أعضاء الجهة", request_member: "طلب صلاحية لزميل", member_email: "البريد الإلكتروني",
			member_name: "الاسم الكامل", member_level: "مستوى الصلاحية", member_requested: "تم إرسال الطلب إلى المسؤول",
		},
		admin: { warnings: "تنبيهات المسؤول", settings: "فتح إعدادات البوابة" },
	},
};

export function translate(lang, key, vars) {
	const pick = (dict) => key.split(".").reduce((o, k) => (o && o[k] !== undefined ? o[k] : undefined), dict);
	let s = pick(messages[lang] || messages.en);
	if (s === undefined) s = pick(messages.en);
	if (s === undefined) s = key;
	if (vars) Object.entries(vars).forEach(([k, v]) => (s = s.replace(`{${k}}`, v)));
	return s;
}
