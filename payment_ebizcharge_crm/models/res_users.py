
from odoo import models, api, Command
import logging

_logger = logging.getLogger(__name__)


class UserCredentials(models.Model):
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        portal_group_id = self.env.ref('base.group_portal').id
        portal_vals, regular_vals = [], []
        for val in vals_list:
            is_portal = any(
                isinstance(cmd, (list, tuple))
                and cmd[0] == Command.SET
                and portal_group_id in (cmd[2] or [])
                for cmd in val.get('group_ids', [])
            )
            (portal_vals if is_portal else regular_vals).append(val)

        portal_users = super(UserCredentials, self.with_context({'portal_user': True})).create(portal_vals) if portal_vals else self.env['res.users']
        regular_users = super().create(regular_vals) if regular_vals else self.env['res.users']
        return portal_users + regular_users

    def _check_credentials(self, password, env):
        result = super()._check_credentials(password, env)
        instances = self.env['ebizcharge.instance.config'].sudo().search(
            [('is_valid_credential', '=', True), ('is_active', '=', True)])
        web_sale = self.env['ir.module.module'].sudo().search(
            [('name', '=', 'website_sale'), ('state', 'in', ['installed', 'to upgrade', 'to remove'])])
        ebiz_obj = self.env['ebiz.charge.api']
        for instance in instances:
            if instance.ebiz_security_key:
                try:
                    ebiz = ebiz_obj.sudo().with_context({'login': True}).get_ebiz_charge_obj(instance=instance)
                    resp, card_verification = self.sudo().merchant_details(ebiz)
                    if resp and card_verification:
                        self._apply_merchant_data(instance, resp, card_verification, web_sale)
                    surcharge_integration_resp = self.sudo().integration_surcharge_details(ebiz)
                    self._apply_surcharge_settings(instance, resp, surcharge_integration_resp)
                    if resp['IsSurchargeEnabled'] and resp['SurchargeTypeId'] == 'DailyDiscount':
                        surcharge_resp = self.sudo().surcharge_details(ebiz)
                        batch_res = [sub['SettingValue'] for sub in surcharge_integration_resp if
                                     sub['SettingName'] == 'BatchProcessingSurchargeTermsNote']
                        instance.surcharge_percentage = surcharge_resp['SurchargePercentage']
                        instance.batch_terms = batch_res[0]
                        instance.surcharge_caption = surcharge_resp['SurchargeCaption']
                        instance.surcharge_terms = surcharge_resp['SurchargeTermsNote']
                except Exception as e:
                    _logger.warning("Connectivity Issue: %s", e)
        return result

    def _apply_merchant_data(self, instance, resp, card_verification, web_sale):
        instance.merchant_data = resp['AllowACHPayments']
        instance.merchant_card_verification = card_verification
        instance.verify_card_before_saving = resp['VerifyCreditCardBeforeSaving']
        instance.use_full_amount_for_avs = resp['UseFullAmountForAVS']
        instance.allow_credit_card_pay = resp['AllowCreditCardPayments']
        instance.enable_cvv = resp['EnableCVVWarnings']
        if web_sale and instance.is_website:
            for w in instance.website_ids:
                w.merchant_data = resp['AllowACHPayments']
                w.merchant_card_verification = card_verification
                w.verify_card_before_saving = resp['VerifyCreditCardBeforeSaving']
                w.allow_credit_card_pay = resp['AllowCreditCardPayments']
                w.enable_cvv = resp['EnableCVVWarnings']

    def _apply_surcharge_settings(self, instance, resp, surcharge_integration_resp):
        instance.is_surcharge_enabled = resp['IsSurchargeEnabled']
        instance.surcharge_type_id = resp['SurchargeTypeId']
        ebiz_emv_pre_auth = next(
            (sur['SettingValue'] for sur in surcharge_integration_resp if sur['SettingName'] == 'IsEMVPreAuthEnabled'),
            None)
        use_econnect_transaction_receipt = next(
            (sur['SettingValue'] for sur in surcharge_integration_resp if sur['SettingName'] == 'UseEConnectTransactionReceipts'),
            None)
        merchant_toggle_sur_per_txn = next(
            (sur['SettingValue'] for sur in surcharge_integration_resp if sur['SettingName'] == 'MerchantCanEnableOrDisableSurchargePerTransaction'),
            None)
        instance.merchant_toggle_sur_per_txn = merchant_toggle_sur_per_txn == 'True'
        instance.is_emv_pre_auth = ebiz_emv_pre_auth == 'True'
        instance.use_econnect_transaction_receipt = use_econnect_transaction_receipt == 'True'

    def merchant_details(self, ebiz):
        try:
            resp = ebiz.client.service.GetMerchantTransactionData(**{
                'securityToken': ebiz._generate_security_json()
            })
        except Exception:
            return None, None

        if resp['UseFullAmountForAVS']:
            card_verification = 'full-amount'
        elif resp['VerifyCreditCardBeforeSaving']:
            card_verification = 'minimum-amount'
        else:
            card_verification = 'no-validation'
        return resp, card_verification

    def surcharge_details(self, ebiz):
        try:
            return ebiz.client.service.GetSurchargeSettings(**{
                'securityToken': ebiz._generate_security_json()
            })
        except Exception:
            return None

    def integration_surcharge_details(self, ebiz):
        try:
            return ebiz.client.service.GetMerchantIntegrationSettings(**{
                'securityToken': ebiz._generate_security_json()
            })
        except Exception:
            return None
