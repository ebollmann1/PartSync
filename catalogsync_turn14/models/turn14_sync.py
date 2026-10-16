"""Queue entry points; native record mapping lives in the two import helpers."""
import logging

from odoo import api, models, _
from odoo.exceptions import AccessError, UserError
from odoo.addons.queue_job.exception import RetryableJobError

from ..services.client import Turn14Error
from ..services.mapping import normalize_item

_logger = logging.getLogger(__name__)

JOBS = {
    "brand": "job_sync_brand",
    "brands": "job_sync_brands",
    "locations": "job_sync_locations",
    "items": "job_sync_items_page",
    "pricing": "job_sync_pricing_page",
    "inventory": "job_sync_inventory_page",
    "images": "job_sync_item_images",
}


class Turn14Sync(models.AbstractModel):
    _name = "turn14.sync"
    _description = "Turn 14 Imports"

    def _company_scope(self, company_id, environment=None):
        """Return an administrator-authorized environment limited to one company."""
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Only administrators can run Turn 14 imports."))
        company = self.env["res.company"].browse(company_id).exists()
        if not company or company not in self.env.user.company_ids:
            raise AccessError(_("You cannot import Turn 14 data for this company."))
        if environment and environment != company.t14_environment:
            raise UserError(_("The company's Turn 14 environment has changed. Start a new import."))
        scoped = self.with_company(company).with_context(allowed_company_ids=[company.id])
        return scoped, company.with_env(scoped.env)

    def _enqueue(self, resource, company, page=1, offset=0, brand_id=None):
        """Queue a resource page with a stable identity across all entry points."""
        scoped, company = self._company_scope(company.id, company.t14_environment)
        identity_key = f"t14.{resource}.{company.id}.{company.t14_environment}.p{page}"
        description = f"Turn 14: {resource.title()} / {company.name} / Page {page}"
        if resource in {"brand", "items"}:
            if not brand_id:
                raise UserError(_("A brand ID is required for this Turn 14 import."))
            identity_key += f".b{brand_id}"
            description += f" / Brand {brand_id}"
            if offset:
                identity_key += f".o{offset}"
                description += f" (Offset {offset})"
        delay = scoped.with_delay(
            identity_key=identity_key,
            description=description,
            channel="root.turn14",
            max_retries=5,
        )
        kwargs = {"environment": company.t14_environment}
        if resource == "items":
            kwargs["page"] = page
            kwargs["offset"] = offset
            kwargs["brand_id"] = str(brand_id)
        elif resource == "brand":
            kwargs["brand_id"] = str(brand_id)
        elif resource != "locations":
            kwargs["page"] = page
        return getattr(delay, JOBS[resource])(company.id, **kwargs)

    def _fetch(self, company, resource, page=1, brand_id=None):
        """Fetch one API resource page and convert retryable failures for queue_job."""
        try:
            with company._get_t14_client() as client:
                if resource == "locations":
                    return client.get_locations(), None
                if resource == "items":
                    return client.get_items_by_brand(brand_id, page=page)
                return getattr(client, f"get_{resource}")(page=page)
        except Turn14Error as exc:
            if exc.retryable:
                raise RetryableJobError(str(exc), seconds=exc.retry_after or 30) from exc
            raise UserError(str(exc)) from exc

    @api.model
    def job_sync_brand(self, company_id, brand_id, environment=None):
        """Ensure one configured brand exists as an Odoo attribute value."""
        scoped, company = self._company_scope(company_id, environment)
        configured_brand_ids = company._get_t14_brand_ids()
        brand_id = str(brand_id)
        if brand_id not in configured_brand_ids:
            raise UserError(_("Brand ID %s is no longer configured for this company.", brand_id))
        brand = scoped._ensure_brand(company, brand_id)
        return {"imported": bool(brand), "brand_id": brand_id}

    @api.model
    def job_sync_brands(self, company_id, page=1, auto_continue=True, environment=None):
        """Import one full-catalog brand page for backward-compatible queued jobs."""
        scoped, company = self._company_scope(company_id, environment)
        brands, next_page = scoped._fetch(company, "brands", page)
        for brand in brands:
            scoped._import_brand(company, brand)
        if auto_continue and next_page:
            scoped._enqueue("brands", company, next_page)
        return {"imported": len(brands), "next_page": next_page}

    @api.model
    def job_sync_locations(self, company_id, environment=None):
        """Import every Turn 14 distribution location for one company."""
        scoped, company = self._company_scope(company_id, environment)
        locations, _next_page = scoped._fetch(company, "locations")
        return {"imported": scoped._import_locations(company, locations)}

    @api.model
    def job_sync_reference_data(self, company_id):
        """Compatibility with already queued combined reference-data jobs."""
        scoped, company = self._company_scope(company_id)
        scoped._enqueue("brands", company)
        scoped._enqueue("locations", company)

    def _enqueue_images(self, company, image_queue, page=1, offset=0):
        """Queue deferred image downloads using their own worker channel."""
        scoped, company = self._company_scope(company.id, company.t14_environment)
        identity_key = f"t14.images.{company.id}.{company.t14_environment}.p{page}"
        description = f"Turn 14: Images / {company.name} / Page {page}"
        if offset:
            identity_key += f".o{offset}"
            description += f" (Offset {offset})"
        delay = scoped.with_delay(
            identity_key=identity_key,
            description=description,
            channel="root.turn14.images",
            max_retries=3,
        )
        return delay.job_sync_item_images(company.id, image_queue)

    @api.model
    def job_sync_item_images(self, company_id, image_queue, environment=None):
        """Download missing product images without blocking catalog imports."""
        import requests
        scoped, company = self._company_scope(company_id, environment)
        products = scoped.env["product.product"].with_company(company)
        imported = 0
        with requests.Session() as session:
            for product_id, url in image_queue:
                product = products.browse(product_id).exists()
                if product and not product.image_1920:
                    if scoped._import_item_image(product, url, session=session):
                        imported += 1
        _logger.info("Turn 14 company=%s imported %s/%s images", company.id, imported, len(image_queue))
        return {"imported_images": imported, "total": len(image_queue)}

    @api.model
    def job_sync_items_page(
        self, company_id, brand_id=None, page=1, offset=0,
        auto_continue=True, environment=None,
    ):
        """Ensure the selected brand exists, then import one page of its products."""
        scoped, company = self._company_scope(company_id, environment)
        if not brand_id:
            configured_brand_ids = company._get_t14_brand_ids()
            for configured_brand_id in configured_brand_ids:
                scoped._enqueue("items", company, brand_id=configured_brand_id)
            return {"queued_brands": len(configured_brand_ids)}
        scoped = scoped.with_context(
            lang=None,
            tracking_disable=True,
            mail_create_nosubscribe=True,
            mail_create_nolog=True,
            mail_notrack=True,
            mail_auto_delete=True,
            skip_default_code=True,
            skip_t14_identity_check=True,
            skip_cpm_update=True,
        )
        configured_brand_ids = company._get_t14_brand_ids()
        brand_id = str(brand_id)
        if brand_id not in configured_brand_ids:
            raise UserError(_("Brand ID %s is no longer configured for this company.", brand_id))
        if page == 1:
            scoped._ensure_brand(company, brand_id)
        items, next_page = scoped._fetch(company, "items", page, brand_id=brand_id)
        batch_size = company.t14_product_batch_size if company.t14_product_batch_size > 0 else 500

        # Pre-lock products once for this batch to prevent lock thrashing
        scoped._lock_reference(f"products:{company.id}")

        items_to_process = items[offset : offset + batch_size]

        # Batch lookup existing products for only this queue job's item slice.
        raw_ids = [
            str(row.get("id") or "").strip()
            for row in items_to_process
            if isinstance(row, dict) and row.get("id")
        ]
        existing_prods = scoped.env["product.product"].with_context(active_test=False)
        existing_map = {
            p.t14_item_id: p
            for p in existing_prods.search([
                ("company_id", "=", company.id),
                ("t14_item_id", "in", raw_ids),
            ])
        } if raw_ids else {}

        cache = {
            "brands": {},
            "categories": {},
            "pricelists": {},
            "item_flags": scoped._get_cached_item_flags(),
            "existing_products": existing_map,
        }
        image_queue = []
        counts = {"created": 0, "updated": 0, "skipped": 0}

        normalized_items = []
        for raw in items_to_process:
            try:
                normalized_items.append(normalize_item(raw))
            except ValueError as exc:
                raise UserError(_(
                    "Invalid Turn 14 item on page %(page)s: %(error)s",
                    page=page, error=str(exc),
                )) from exc
        counts = scoped._import_items_batch(
            company, normalized_items, cache, image_queue,
        )

        _logger.info(
            "Turn 14 company=%s brand=%s page=%s (items: %s): %s",
            company.id, brand_id, page, len(items_to_process), counts,
        )

        if auto_continue and not company.t14_test_import:
            next_offset = offset + len(items_to_process)
            if next_offset < len(items):
                scoped._enqueue(
                    "items", company, page=page, offset=next_offset,
                    brand_id=brand_id,
                )
            elif next_page:
                scoped._enqueue(
                    "items", company, page=next_page, offset=0,
                    brand_id=brand_id,
                )
        return counts

    def _sync_supplier_snapshot(self, company_id, resource, page, auto_continue, environment):
        """Legacy jobs keep raw optional feeds in native company attachments.

        Supplier assignment and pricing are deferred until the vendor is known.
        No supplier information or stock quantity is changed by these jobs.
        """
        import json

        scoped, company = self._company_scope(company_id, environment)
        entries, next_page = scoped._fetch(company, resource, page)
        name = f"Turn14 {company.t14_environment} {resource} page {page}.json"
        attachments = scoped.env["ir.attachment"]
        attachment = attachments.search([
            ("res_model", "=", "res.company"), ("res_id", "=", company.id),
            ("company_id", "=", company.id), ("name", "=", name),
        ], limit=1)
        vals = {"name": name, "res_model": "res.company", "res_id": company.id,
                "company_id": company.id, "type": "binary", "mimetype": "application/json",
                "public": False, "raw": json.dumps(entries).encode()}
        if attachment:
            attachment.write(vals)
        else:
            attachments.create(vals)
        if auto_continue and next_page:
            scoped._enqueue(resource, company, next_page)

    @api.model
    def job_sync_pricing_page(self, company_id, page=1, auto_continue=True, environment=None):
        return self._sync_supplier_snapshot(company_id, "pricing", page, auto_continue, environment)

    @api.model
    def job_sync_inventory_page(self, company_id, page=1, auto_continue=True, environment=None):
        return self._sync_supplier_snapshot(company_id, "inventory", page, auto_continue, environment)
