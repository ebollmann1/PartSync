# -*- coding: utf-8 -*-
"""Reference imports: shared brand attributes and company distribution centers."""

from odoo import _, models
from odoo.exceptions import UserError
from odoo.addons.queue_job.exception import RetryableJobError
from odoo.tools.sql import escape_psql

from ..services.client import Turn14Error


class Turn14Reference(models.AbstractModel):
    _inherit = "turn14.sync"

    def _lock_reference(self, key):
        """Serialize imports using the same shared or company identity."""
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            ("catalogsync_turn14:" + key,),
        )

    def _external_record(self, xml_id, model):
        record = self.env.ref(xml_id, raise_if_not_found=False)
        if record and record._name != model:
            raise UserError(_("Turn 14 external ID %s points to an unexpected model.", xml_id))
        return record.exists() if record else self.env[model]

    def _upsert_ir_model_data(self, model, res_id, full_xml_id):
        """Keep existing source identities, including the original brand XML IDs.

        Writing the identity also makes stale concurrent imports fail with a
        serialization error under Odoo's repeatable-read isolation. A waiting
        advisory lock alone cannot refresh a transaction's existing snapshot.
        """
        module, name = full_xml_id.split(".", 1)
        data = self.env["ir.model.data"].search([
            ("module", "=", module), ("name", "=", name),
        ], limit=1)
        values = {"model": model, "res_id": res_id, "noupdate": True}
        if data:
            if data.res_id != res_id or data.model != model:
                data.write(values)
        else:
            data = self.env["ir.model.data"].create({
                **values, "module": module, "name": name,
            })
        return data

    def _batch_bind_sources(self, records_with_source_ids, company, resource):
        """Batch-bind source IDs with one SQL upsert instead of N ORM calls."""
        if not records_with_source_ids:
            return
        prefix = f"{resource}_{company.id}_"
        env = company.t14_environment
        model_name = records_with_source_ids[0][0]._name
        record_ids = [r.id for r, _sid in records_with_source_ids]

        # One query: fetch existing bindings to detect environment conflicts
        self.env.cr.execute(
            """
            SELECT res_id, name FROM ir_model_data
            WHERE module = 'catalogsync_turn14'
              AND model = %s
              AND res_id = ANY(%s)
              AND name LIKE %s
            """,
            (model_name, record_ids, escape_psql(prefix) + '%'),
        )
        existing_names = {}
        for res_id, name in self.env.cr.fetchall():
            existing_names.setdefault(res_id, set()).add(name)

        entries = []
        for record, source_id in records_with_source_ids:
            expected = f"{prefix}{env}_{source_id}"
            bound = existing_names.get(record.id, set())
            if bound - {expected}:
                raise UserError(_(
                    "This Turn 14 record is already mapped to a different "
                    "environment or source ID."
                ))
            entries.append((model_name, record.id, 'catalogsync_turn14', expected))

        # One query: batch upsert all source bindings
        uid = self.env.uid
        args = []
        placeholders = []
        for model, res_id, module, name in entries:
            placeholders.append(
                "(%s, %s, %s, %s, true, %s, %s, "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')"
            )
            args.extend([module, name, model, res_id, uid, uid])
        self.env.cr.execute(
            "INSERT INTO ir_model_data "
            "(module, name, model, res_id, noupdate, create_uid, write_uid, "
            "create_date, write_date) VALUES "
            + ", ".join(placeholders)
            + " ON CONFLICT (module, name) DO UPDATE SET "
            "res_id = EXCLUDED.res_id, model = EXCLUDED.model, "
            "noupdate = true, write_uid = EXCLUDED.write_uid, "
            "write_date = EXCLUDED.write_date",
            args,
        )
        self.env['ir.model.data'].invalidate_model()

    def _get_or_create_brand_attribute(self):
        """Reuse Brand regardless of variant mode, including archived attributes."""
        self._lock_reference("brands")
        attributes = self.env["product.attribute"].with_context(active_test=False, lang=None)
        attribute = attributes.search([("name", "=ilike", "Brand")], order="id", limit=1)
        if not attribute:
            attribute = self._external_record(
                "catalogsync_turn14.brand_attribute", "product.attribute",
            )
        if not attribute:
            attribute = attributes.create({"name": "Brand", "create_variant": "no_variant"})
        elif not attribute.active:
            attribute.active = True
        self._upsert_ir_model_data(
            "product.attribute", attribute.id, "catalogsync_turn14.brand_attribute",
        )
        return attribute

    def _import_brand(self, company, raw_brand):
        """Normalize one API brand record into the shared Brand attribute."""
        attrs = raw_brand.get("attributes") or {}
        return self._resolve_brand_value(
            company, attrs.get("name") or attrs.get("Name"), raw_brand.get("id"),
        )

    def _ensure_brand(self, company, brand_id):
        """Import a configured brand from the API only when its value is missing."""
        brand_id = str(brand_id)
        attribute = self._get_or_create_brand_attribute()
        values = self.env["product.attribute.value"].with_context(active_test=False)
        brand = values.search([
            ("attribute_id", "=", attribute.id),
            ("t14_brand_id", "=", brand_id),
        ], limit=1)
        if brand:
            if not brand.active:
                brand.active = True
            return brand
        try:
            with company._get_t14_client() as client:
                raw_brand = client.get_brand(brand_id)
        except Turn14Error as exc:
            if exc.retryable:
                raise RetryableJobError(str(exc), seconds=exc.retry_after or 30) from exc
            raise UserError(str(exc)) from exc
        if str(raw_brand.get("id") or "") != brand_id:
            raise UserError(_("Turn 14 returned a different brand than the requested ID %s.", brand_id))
        return self._import_brand(company, raw_brand)

    def _bind_source(self, record, company, resource, source_id):
        """Environment identity lives in native external IDs, not extra fields."""
        prefix = f"{resource}_{company.id}_"
        name = f"{prefix}{company.t14_environment}_{source_id}"
        other = self.env["ir.model.data"].search([
            ("module", "=", "catalogsync_turn14"), ("model", "=", record._name),
            ("res_id", "=", record.id), ("name", "=like", escape_psql(prefix) + "%"),
            ("name", "!=", name),
        ], limit=1)
        if other:
            raise UserError(_("This Turn 14 record is already mapped to a different environment or source ID."))
        self._upsert_ir_model_data(record._name, record.id, "catalogsync_turn14." + name)

    def _resolve_brand_value(self, company, brand_name, brand_id):
        """Match the exact name first, then source ID, and create only if needed."""
        company.ensure_one()
        name = str(brand_name or "").strip()
        source_id = str(brand_id).strip() if brand_id is not None else ""
        values = self.env["product.attribute.value"].with_context(active_test=False, lang=None)
        if not name and not source_id:
            return values

        attribute = self._get_or_create_brand_attribute()
        value = values.search([
            ("attribute_id", "=", attribute.id),
            ("name", "=ilike", escape_psql(name)),
        ], order="id", limit=1) if name else values
        xml_id = (
            f"catalogsync_turn14.brand_{company.t14_environment}_{source_id}"
            if source_id else None
        )
        if not value and source_id:
            value = values.search([
                ("attribute_id", "=", attribute.id), ("t14_brand_id", "=", source_id),
            ], limit=1)
        if not value and xml_id:
            value = self._external_record(xml_id, "product.attribute.value")
            if value and value.attribute_id != attribute:
                raise UserError(_(
                    "Turn 14 brand %(brand)s is already linked to attribute %(attribute)s. "
                    "Resolve that existing mapping before importing this brand.",
                    brand=source_id, attribute=value.attribute_id.display_name,
                ))
        if value and name and value.with_context(lang=None).name.casefold() != name.casefold():
            value.with_context(lang=None).name = name
        if not value and name:
            value = values.create({"attribute_id": attribute.id, "name": name})
        if value:
            if not value.active:
                value.active = True
            if xml_id:
                if value.t14_brand_id and value.t14_brand_id != source_id:
                    raise UserError(_("Brand %(name)s already has Turn 14 ID %(id)s.", name=value.name, id=value.t14_brand_id))
                value.t14_brand_id = source_id
                self._upsert_ir_model_data("product.attribute.value", value.id, xml_id)
        return value

    def _get_parent_stock_location(self, company):
        warehouse = self._external_record("stock.warehouse0", "stock.warehouse")
        if not warehouse or warehouse.company_id != company:
            warehouse = self.env["stock.warehouse"].with_company(company).search([
                ("company_id", "=", company.id),
            ], order="id", limit=1)
        return warehouse.lot_stock_id

    def _import_locations(self, company, locations_data):
        company.ensure_one()
        if not locations_data:
            return 0
        parent_location = self._get_parent_stock_location(company)
        locations = self.env["stock.location"].with_company(company).with_context(active_test=False)
        imported = 0
        for raw in locations_data:
            source_id = str(raw.get("id") or "").strip()
            if not source_id:
                continue
            attrs = raw.get("attributes") or {}
            name = (attrs.get("Name") or attrs.get("name") or f"DC {source_id}").strip()
            location = locations.search([
                ("company_id", "=", company.id),
                ("t14_location_id", "=", source_id),
            ], order="id", limit=1)
            vals = {
                "name": name,
                "usage": "internal",
                "active": True,
                "location_id": parent_location.id,
                "company_id": company.id,
                "t14_location_id": source_id,
            }
            if location:
                location.write(vals)
            else:
                location = locations.create(vals)
            self._bind_source(location, company, "location", source_id)
            imported += 1
        return imported
