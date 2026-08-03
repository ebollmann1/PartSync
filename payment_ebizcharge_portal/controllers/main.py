import logging
from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo import http
from odoo.http import request, route
from odoo.exceptions import ValidationError
_logger = logging.getLogger(__name__)
from odoo.tools.translate import LazyTranslate, _
_lt = LazyTranslate(__name__)


class EbizchargeController(http.Controller):
    _approved_url = '/payment/ebizcharge/approved'
    _decline_url = '/payment/ebizcharge/cancel'
    _error_url = '/payment/ebizcharge/error'

    @http.route(['/surcharge/check'], type='jsonrpc', auth='public', csrf=False, website=True)
    def surcharge_check_data(self, verify_validity=False, **kwargs):
        surcharge_calc_amt = 0
        kwargs = kwargs['kwargs']
        partner = request.env.user.partner_id
        if partner.ebiz_profile_id:
            ebiz = request.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=partner.ebiz_profile_id)
        else:
            profile = request.env['ebizcharge.instance.config'].sudo().search(
                [('website_ids', 'in', request.website.ids), ('is_website', '=', True)], limit=1)
            ebiz = request.env['ebiz.charge.api'].get_ebiz_charge_obj(instance=profile)
        if ebiz:
            methodid = kwargs['pm_id'] if 'pm_id' in kwargs else 0
            method_id = request.env['payment.token'].search([('id', '=', int(methodid)), ('token_type', '=', 'credit')],
                                                            limit=1)
            params = {
                'securityToken': ebiz._generate_security_json(),
                'customerInternalId': partner.ebiz_internal_id,
                'amount': float(kwargs['amount']),
            }
            if method_id:
                params.update({
                    'paymentMethodId': method_id.ebizcharge_profile,
                    'cardZipCode': method_id.avs_zip,
                })
            else:
                params.update({
                    'cardNumber': kwargs['cc_number'].replace(' ', '') if 'cc_number' in kwargs else 0,
                    'cardZipCode': kwargs['avs_zip'] if 'avs_zip' in kwargs else 0,
                })

            resp = ebiz.client.service.CalculateSurchargeAmount(**params)
            surcharge_calc_amt = float(resp['SurchargeAmount'])
        res = {
            'amount': surcharge_calc_amt,
        }
        return res

    @http.route(['/payment/ebizcharge/s2s/create_json_3ds'], type='jsonrpc', auth='public', csrf=False)
    def ebizcharge_s2s_create_json_3ds(self, verify_validity=False, **kwargs):
        token = False
        kwargs = kwargs['kwargs']
        acquirer = request.env['payment.provider'].sudo().browse(int(kwargs['acquirer_id']))
        is_manage_screen = False
        kwargs['web_pay'] = '1'
        try:
            if not kwargs.get('partner_id') and not request.env.user._is_public():
                kwargs = dict(kwargs, partner_id=request.env.user.partner_id.id)
            website_id = request.website_routing
            if kwargs.get('partner_id'):
                token = acquirer.with_context({'website': website_id}).s2s_process(kwargs)
        except ValidationError as e:
            _logger.exception(e)
            message = e.args[0]
            if isinstance(message, dict) and 'missing_fields' in message:
                msg = _("The transaction cannot be processed because some contact details are missing or invalid: ")
                message = msg + ', '.join(message['missing_fields']) + '. '
                if request.env.user._is_public():
                    message += _("Please sign in to complete your profile.")
                    if request.env['ir.config_parameter'].sudo().get_param('auth_signup.allow_uninvited', 'False').lower() == 'false':
                        message += _("If you don't have any account, please ask your salesperson to update your profile. ")
                else:
                    message += _("Please complete your profile.")

            return {
                'error': message
            }

        if not token and not request.env.user._is_public():
            res = {
                'result': False,
                'is_manage_screen': is_manage_screen,
            }
            return res

        res = {
            'result': True,
            'is_manage_screen': is_manage_screen,
            'id': token.id if token else False,
            '3d_secure': False,
            'verified': token.id if token else False,
            'providerid': token.provider_id.id if token else False,
        }
        return res

    @http.route(['/payment/ebizcharge/get/token'], type='jsonrpc', auth='public', csrf=False)
    def ebizcharge_get_token_info(self, **kwargs):
        return request.env['payment.token'].get_payment_token_information(kwargs['pm_id'])

    @http.route(['/delete/ebizcharge/token'], type='jsonrpc', auth='public', csrf=False)
    def ebizcharge_delete_token_info(self, **kwargs):
        payment_token_id = request.env['payment.token'].sudo().browse(kwargs['pm_id']).exists()
        if payment_token_id:
            payment_token_id.token_action_archive()
            return 'success'
        return 'No record found for unique ID %s. It may have been deleted.' % (kwargs['pm_id'])


class EbizChargeWebsiteSale(WebsiteSale):

    def _get_shop_payment_values(self, order, **kwargs):
        render_values = super()._get_shop_payment_values(order, **kwargs)
        profile = request.env.user.partner_id.ebiz_profile_id or self.env['ebizcharge.instance.config'].sudo().search(
            [('website_ids', 'in', request.website.ids), ('is_website', '=', True), ('is_active', '=', True)], limit=1)
        show_ach = profile.merchant_data
        show_credit_cards = profile.allow_credit_card_pay
        allowed_commands = profile.ebiz_website_allowed_command
        auth_only = allowed_commands == 'pre-auth'
        odoo_partner = request.env['res.partner'].sudo().browse(render_values['partner'].id).ensure_one()
        payment_tokens = odoo_partner.payment_token_ids
        payment_tokens |= odoo_partner.commercial_partner_id.sudo().payment_token_ids
        card_narrations = profile.surcharge_terms
        is_sur_able = False
        surcharge_terms = ''
        if profile.is_surcharge_enabled and profile.surcharge_type_id == 'DailyDiscount':
            is_sur_able = True
            surcharge_terms = profile.surcharge_terms
        render_values['tokens_sudo'] = render_values['tokens_sudo'].filtered(lambda i: i.provider_id.code != 'ebizcharge')
        render_values['cardNarrations'] = card_narrations
        render_values['is_sur_able'] = is_sur_able
        render_values['allow_pay_surcharge'] = bool(profile.is_surcharge_enabled)
        render_values['surcharge_percent'] = profile.surcharge_percentage if profile.is_surcharge_enabled else 0
        render_values['surcharge_amount'] = 0.00
        render_values['show_surcharge_amt'] = False
        render_values['surcharge_terms'] = surcharge_terms
        render_values['tokens'] = payment_tokens.filtered(
            lambda r: r.partner_id == request.env.user.partner_id and r.provider_id.code != "ebizcharge")
        render_values['ebiz_tokens'] = payment_tokens.filtered(
            lambda r: r.partner_id == request.env.user.partner_id and r.provider_id.code == "ebizcharge")
        render_values['logIn'] = bool(request.session['session_token'])
        render_values['showACH'] = show_ach
        render_values['showCreditCards'] = show_credit_cards
        render_values['authOnly'] = auth_only
        return render_values

    def _prepare_shop_payment_confirmation_values(self, order):
        values = super()._prepare_shop_payment_confirmation_values(order)
        values['surcharge_amount'] = 0.0
        values['surcharge_percent'] = 0.0
        if order.transaction_ids:
            values['surcharge_amount'] = order.transaction_ids[0].surcharge_amt if order.partner_id.ebiz_profile_id.is_surcharge_enabled else 0
            values['surcharge_percent'] = order.transaction_ids[0].surcharge_percent if order.partner_id.ebiz_profile_id.is_surcharge_enabled else 0
        values['allow_pay_surcharge'] = bool(order.partner_id.ebiz_profile_id.is_surcharge_enabled)
        values['is_add_surcharge'] = bool(order.partner_id.ebiz_profile_id.is_surcharge_enabled)
        return values
