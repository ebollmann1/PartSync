/** @odoo-module **/
import { _t } from "@web/core/l10n/translation";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { omit } from "@web/core/utils/objects";

import { CopyButton } from "@web/core/copy_button/copy_button";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { UrlField } from "@web/views/fields/url/url_field";

import { Component } from "@odoo/owl";

class CopyToClipboardField extends Component {
    static template = "payment_ebizcharge_crm.CopyToClipboardField";
    static props = {
        ...standardFieldProps,
        string: { type: String, optional: true },
        disabledExpr: { type: String, optional: true },
    };

    setup() {
        this.copyText = this.props.string || _t("Copy");
        this.successText = _t("Copied to clipboard");
    }

    get copyButtonClassName() {
        return `o_btn_${this.type}_copy btn-sm`;
    }
    get fieldProps() {
        return omit(this.props, "string", "disabledExpr");
    }
    get type() {
        return this.props.record.fields[this.props.name].type;
    }
    get disabled() {
        return this.props.disabledExpr
            ? evaluateBooleanExpr(
                  this.props.disabledExpr,
                  this.props.record.evalContextWithVirtualIds
              )
            : false;
    }
}

export class CopyToClipboardLinkField extends CopyToClipboardField {
    static components = { Field: UrlField, CopyButton };

    get copyButtonIcon() {
        return "fa-clone align-baseline";
    }
}

function extractProps({ attrs }) {
    return {
        string: attrs.string,
        disabledExpr: attrs.disabled,
    };
}

export const copyToClipboardLinkField = {
    component: CopyToClipboardLinkField,
    displayName: _t("Copy URL to Clipboard"),
    supportedTypes: ["char"],
    extractProps,
};

registry.category("fields").add("CopyClipboardLink", copyToClipboardLinkField);