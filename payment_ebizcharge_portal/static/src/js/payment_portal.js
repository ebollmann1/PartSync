/** @odoo-module **/

$(function () {
    const updateOrNot = $('input[name="update_pm_id"]').val();
    if (updateOrNot === "") {
        $('input#cc_number').payment('formatCardNumber');
        $('input#account_number').payment('formatAccountNumber');
        $('input#routing_number').payment('formatRoutingNumber');
    }
    $('input#cc_cvc').payment('formatCardCVC');
    $('input#cc_expiry').payment('formatCardExpiry');
    $('input[name="security-code"]').payment('formatSecurityCode');

    $('input#cc_number').on('focusout', function (e) {
        const updateOrNot = $('input[name="update_pm_id"]').val();
        if (updateOrNot === "") {
            const valid_value = $.payment.validateCardNumber(this.value);
            const card_type = $.payment.cardType(this.value);
            if (card_type) {
                $(this).parent('.form-group').children('.card_placeholder').removeClass().addClass('card_placeholder ' + card_type);
                $(this).parent('.form-group').children('input[name="cc_brand"]').val(card_type);
            } else {
                $(this).parent('.form-group').children('.card_placeholder').removeClass().addClass('card_placeholder');
            }
            if (valid_value) {
                applyValidValueClasses(this);
                $(this).siblings('.o_invalid_field').remove();
            } else {
                applyInValidValueClasses(this);
            }
        } else {
            applyValidValueClasses(this);
            $(this).siblings('.o_invalid_field').remove();
        }
    });

    $('input#cc_cvc').on('focusout', function (e) {
        const updateOrNot = $('input[name="update_pm_id"]').val();
        if (updateOrNot === "") {
            const cc_nbr = $(this).parents('#addCardDetails').find('#cc_number').val();
            const card_type = $.payment.cardType(cc_nbr);
            const valid_value = $.payment.validateCardCVC(this.value, card_type);
            if (valid_value) {
                applyValidValueClasses(this);
                $(this).siblings('.o_invalid_field').remove();
            } else {
                applyInValidValueClasses(this);
            }
        } else {
            const odoo_card_type = $('input[name="card_type"]').val();
            const card_type = getCardType(odoo_card_type);
            const valid_value = $.payment.validateCardCVC(this.value, card_type);
            if (valid_value) {
                applyValidValueClasses(this);
                $(this).siblings('.o_invalid_field').remove();
            } else {
                applyInValidValueClasses(this);
            }
        }
    });

    $('input#cc_holder_name').on('focusout', function (e) {
        $(this).parent('.form-group').removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
        $(this).siblings('.o_invalid_field').remove();
    });

    $('input#avs_street').on('focusout', function (e) {
        $(this).parent('.form-group').removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
        $(this).siblings('.o_invalid_field').remove();
    });

    $('input#avs_zip').on('focusout', function (e) {
        const valid_value = validateZipCode(this.value);
        if (valid_value) {
            applyValidValueClasses(this);
            $(this).siblings('.o_invalid_field').remove();
        } else {
            applyInValidValueClasses(this);
        }
    });

    $('input#cc_expiry').on('focusout', function (e) {
        const expiry_value = $.payment.cardExpiryVal(this.value);
        const month = expiry_value.month || '';
        const year = expiry_value.year || '';
        const valid_value = $.payment.validateCardExpiry(month, year);
        if (valid_value) {
            applyValidValueClasses(this);
            $(this).siblings('.o_invalid_field').remove();
        } else {
            applyInValidValueClasses(this);
        }
    });

    $('input#bank_account_holder_name').on('focusout', function (e) {
        $(this).parent('.form-group').removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
        $(this).siblings('.o_invalid_field').remove();
    });

    $('select#bank_account_type').on('change', function (e) {
        $(this).parent('.form-group').removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
        $(this).siblings('.o_invalid_field').remove();
    });

    $('input#account_number').on('focusout', function (e) {
        const updateOrNot = $('input[name="update_pm_id"]').val();
        if (updateOrNot === "") {
            const valid_value = $.payment.validateAccountNumber(this.value);
            if (valid_value) {
                applyValidValueClasses(this);
                $(this).siblings('.o_invalid_field').remove();
            } else {
                applyInValidValueClasses(this);
            }
        } else {
            applyValidValueClasses(this);
            $(this).siblings('.o_invalid_field').remove();
        }
    });

    $('input#routing_number').on('focusout', function (e) {
        const updateOrNot = $('input[name="update_pm_id"]').val();
        if (updateOrNot === "") {
            const valid_value = $.payment.validateRoutingNumber(this.value);
            if (valid_value) {
                applyValidValueClasses(this);
                $(this).siblings('.o_invalid_field').remove();
            } else {
                applyInValidValueClasses(this);
            }
        } else {
            applyValidValueClasses(this);
            $(this).siblings('.o_invalid_field').remove();
        }
    });

    $('select[name="pm_acquirer_id"]').on('change', function () {
        const acquirer_id = $(this).val();
        $('.acquirer').addClass('d-none');
        $('.acquirer[data-acquirer-id="' + acquirer_id + '"]').removeClass('d-none');
    });

    $('input[name="security-code"]').on('input', function (e) {
        const odoo_card_type = $('input[name="o_payment_radio"]:checked')[0].getAttribute('data-card-type');
        const card_type = getCardType(odoo_card_type);
        const valid_value = $.payment.validateCardCVC(this.value, card_type);

        if (this.value.length === 0) {
            $(this).parent('.form-group').removeClass('o_has_success').find('.form-control, .custom-select').removeClass('is-valid');
            $(this).parent('.form-group').removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
            return;
        }

        if (valid_value) {
            applyValidValueClasses(this);
            $(this).siblings('.o_invalid_field').remove();
        } else {
            applyInValidValueClasses(this);
        }
    });
});

function validateZipCode(value) {
    return value.split('-').every(matchRegex);
}

function applyValidValueClasses(element) {
    $(element).parent('.form-group').addClass('o_has_success').find('.form-control, .custom-select').addClass('is-valid');
    $(element).parent('.form-group').removeClass('o_has_error').find('.form-control, .custom-select').removeClass('is-invalid');
}

function applyInValidValueClasses(element) {
    $(element).parent('.form-group').addClass('o_has_error').find('.form-control, .custom-select').addClass('is-invalid');
    $(element).parent('.form-group').removeClass('o_has_success').find('.form-control, .custom-select').removeClass('is-valid');
}

function matchRegex(element) {
    return element.match(/^[0-9a-zA-Z-]+$/);
}

function getCardType(type) {
    switch (type) {
        case 'M': return 'mastercard';
        case 'V': return 'visa';
        case 'A': return 'amex';
        case 'DS': return 'discover';
        case 'J': return 'jcb';
    }
}

