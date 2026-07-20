from odoo import http
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale

class WebsiteSalePreview(WebsiteSale):

    @http.route(
        '/shop/<model("product.template"):product_template>/document/<int:document_id>',
        type='http',
        auth='public',
        website=True,
        sitemap=False,
        readonly=True,
    )
    def product_document(self, product_template, document_id):
        product_template.check_access('read')

        document = request.env['product.document'].browse(document_id).sudo().exists()
        if not document or not document.active:
            return request.redirect(self._get_shop_path())

        if not document.shown_on_product_page or not (
            document.res_id == product_template.id
            and document.res_model == 'product.template'
        ):
            return request.redirect(self._get_shop_path())

        return request.env['ir.binary']._get_stream_from(
            document.ir_attachment_id,
        ).get_response(as_attachment=True)

    @http.route(
        '/shop/<model("product.template"):product_template>/document/<int:document_id>/preview',
        type='http',
        auth='public',
        website=True,
        sitemap=False,
        readonly=True,
    )
    def product_document_preview(self, product_template, document_id):
        product_template.check_access('read')

        document = request.env['product.document'].browse(document_id).sudo().exists()
        if not document or not document.active:
            return request.redirect(self._get_shop_path())

        if not document.shown_on_product_page or not (
            document.res_id == product_template.id
            and document.res_model == 'product.template'
        ):
            return request.redirect(self._get_shop_path())

        attachment = document.ir_attachment_id
        if attachment.type == 'url':
            return request.redirect(attachment.url)

        return request.env['ir.binary']._get_stream_from(
            attachment,
        ).get_response(as_attachment=False)
