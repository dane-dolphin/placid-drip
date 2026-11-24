"""Undo the HTML-encoding that the LMS edit forms used to apply on every save.

The course, batch, quiz, assignment, program, exercise and job forms ran each
text value through an `escapeHTML` helper before saving, so `Christ's` was stored
as `Christ&#39;s`. The app shows text exactly as stored, so the entity appeared
on screen - and because the form loaded that stored value and encoded it again
on the next save, each edit added another layer (`&amp;amp;amp;#39;`). Image
URLs with a query string were mangled the same way (`=` became `&#x3D;`).

The forms no longer do this. This patch peels every layer off what is already
stored. It only decodes the seven entities that helper produced, only in plain
text columns (rich-text ones were never encoded), and writes with a direct
UPDATE so that no document hooks run and `modified` is left alone. Safe to run
again: a clean value has nothing to decode.
"""

import frappe

DOCTYPES = (
	"LMS Course",
	"LMS Batch",
	"LMS Quiz",
	"LMS Assignment",
	"LMS Program",
	"LMS Programming Exercise",
	"Job Opportunity",
)

PLAIN_TEXT_FIELDTYPES = ("Data", "Small Text", "Text", "Long Text", "Attach", "Attach Image")

#: Exactly what the removed helper produced. `&amp;` is decoded first on each
#: pass so that `&amp;#39;` becomes `&#39;` and then `'`.
ENTITIES = (
	("&amp;", "&"),
	("&lt;", "<"),
	("&gt;", ">"),
	("&quot;", '"'),
	("&#39;", "'"),
	("&#x60;", "`"),
	("&#x3D;", "="),
)

MAX_LAYERS = 30


def decode(value: str) -> str:
	for _ in range(MAX_LAYERS):
		decoded = value
		for entity, char in ENTITIES:
			decoded = decoded.replace(entity, char)
		if decoded == value:
			break
		value = decoded
	return value


def execute():
	fixed = 0

	for doctype in DOCTYPES:
		if not frappe.db.table_exists(doctype):
			continue

		meta = frappe.get_meta(doctype)
		fields = [
			df.fieldname
			for df in meta.fields
			if df.fieldtype in PLAIN_TEXT_FIELDTYPES and frappe.db.has_column(doctype, df.fieldname)
		]

		for fieldname in fields:
			rows = frappe.db.sql(
				f"select name, `{fieldname}` from `tab{doctype}` where `{fieldname}` like %s",
				("%&%;%",),
			)
			for name, value in rows:
				decoded = decode(value)
				if decoded != value:
					frappe.db.sql(
						f"update `tab{doctype}` set `{fieldname}` = %s where name = %s",
						(decoded, name),
					)
					fixed += 1

	frappe.clear_cache()
	print(f"unescape_saved_titles: {fixed} value(s) repaired")
