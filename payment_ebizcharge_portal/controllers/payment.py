from odoo import _, http
from odoo.http import request, route
from odoo.addons.payment.controllers import portal as payment_portal
from odoo.addons.website_sale.controllers.payment import PaymentPortal as website_payment_portal
from odoo.tools import SQL
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from psycopg2.errors import LockNotAvailable
from odoo.fields import Command


class PaymentPortal(payment_portal.PaymentPortal):

    @http.route('/my/orders/<int:order_id>/transaction', type='jsonrpc', auth='public')
    def portal_order_transaction(self, order_id, access_token, **kwargs):
        try:
            order_sudo = self._document_check_access('sale.order', order_id, access_token)
        except MissingError as error:
            raise error
        except AccessError:
            raise ValidationError(_("The access token is invalid."))

        if kwargs.get('token_id'):
            ebiztokenid = request.env['payment.token'].search([('id', '=', int(kwargs['token_id']))], limit=1)
            if ebiztokenid:
                kwargs.update({'provider_id': ebiztokenid.provider_id.id})

        logged_in = not request.env.user._is_public()
        partner_sudo = request.env.user.partner_id if logged_in else order_sudo.partner_invoice_id
        self._validate_transaction_kwargs(kwargs)
        kwargs.update({
            'partner_id': partner_sudo.id,
            'currency_id': order_sudo.currency_id.id,
            'sale_order_id': order_id,
        })
        tx_sudo = self._create_transaction(
            custom_create_values={'sale_order_ids': [Command.set([order_id])]}, **kwargs,
        )
        return tx_sudo._get_processing_values()

    @route('/invoice/transaction/<int:invoice_id>', type='jsonrpc', auth='public')
    def invoice_transaction(self, invoice_id, access_token, **kwargs):
        try:
            invoice_sudo = self._document_check_access('account.move', invoice_id, access_token)
        except MissingError as error:
            raise error
        except AccessError:
            raise ValidationError(_("The access token is invalid."))

        if kwargs.get('token_id') is not None:
            ebiztokenid = request.env['payment.token'].search([('id', '=', int(kwargs['token_id']))], limit=1)
            kwargs.update({'provider_id': ebiztokenid.provider_id.id})

        logged_in = not request.env.user._is_public()
        partner_sudo = request.env.user.partner_id if logged_in else invoice_sudo.partner_id
        self._validate_transaction_kwargs(kwargs)
        kwargs.update({
            'currency_id': invoice_sudo.currency_id.id,
            'partner_id': partner_sudo.id,
            'web_pay': "1",
        })
        kwargs.pop('custom_create_values', None)
        tx_sudo = self._create_transaction(
            custom_create_values={'invoice_ids': [Command.set([invoice_id])]}, **kwargs,
        )
        return tx_sudo._get_processing_values()

    @http.route(['/refresh_payment_profiles'], type='jsonrpc', auth='public')
    def refresh_payment_profiles(self, **kw):
        request.env.user.partner_id.sync_to_ebiz()
        request.env.user.partner_id.refresh_payment_methods(ecom_side=True)
        return {'result': True}


class WebsitePaymentPortal(website_payment_portal):

    @route('/shop/payment/transaction/<int:order_id>', type='jsonrpc', auth='public', website=True)
    def shop_payment_transaction(self, order_id, access_token, **kwargs):
        try:
            order_sudo = self._document_check_access('sale.order', order_id, access_token)
            request.env.cr.execute(
                SQL('SELECT 1 FROM sale_order WHERE id = %s FOR NO KEY UPDATE NOWAIT', order_id)
            )
        except MissingError:
            raise
        except AccessError as e:
            raise ValidationError(_("The access token is invalid.")) from e
        except LockNotAvailable:
            raise UserError(_("Payment is already being processed."))

        if order_sudo.state == "cancel":
            raise ValidationError(_("The order has been cancelled."))

        order_sudo._check_cart_is_ready_to_be_paid()

        self._validate_transaction_kwargs(kwargs)
        kwargs.update({
            'partner_id': order_sudo.partner_invoice_id.id,
            'currency_id': order_sudo.currency_id.id,
            'sale_order_id': order_id,
        })
        if not kwargs.get('amount'):
            kwargs['amount'] = order_sudo.amount_total

        compare_amounts = order_sudo.currency_id.compare_amounts
        if compare_amounts(kwargs['amount'], order_sudo.amount_total):
            raise ValidationError(_("The cart has been updated. Please refresh the page."))
        if compare_amounts(order_sudo.amount_paid, order_sudo.amount_total) == 0:
            raise UserError(_("The cart has already been paid. Please refresh the page."))

        if delay_payment_request := kwargs.get('flow') == 'token':
            request.update_context(delay_payment_request=True, delay_token_charge=True)
        tx_sudo = self._create_transaction(
            custom_create_values={'sale_order_ids': [Command.set([order_id])]}, **kwargs,
        )

        request.session['__website_sale_last_tx_id'] = tx_sudo.id

        self._validate_transaction_for_order(tx_sudo, order_sudo)
        if delay_payment_request:
            tx_sudo.invalidate_recordset(['state'])
            if tx_sudo.state not in ('authorized', 'done', 'cancel', 'error'):
                if 'web_pay' in kwargs:
                    tx_sudo.with_context({'web_pay': kwargs['web_pay'], 'from_portal': True})._send_payment_request()
                else:
                    tx_sudo.sudo().write({'transaction_type': 'pre_auth'})
                    tx_sudo.with_context({'set_done': True, 'from_portal': True, 'web_pay': '1'})._send_payment_request()
        return tx_sudo._get_processing_values()
