from datetime import date

__all__ = [
    '_prepare_billing_address', '_transaction_line', '_transaction_lines',
    '_year_selection_from_current', '_year_selection_from_2000', '_month_selection',
    '_parse_avs_result',
]


def _parse_avs_result(resp):
    # Works with both dict responses and zeep TransactionResponse objects.
    # Zeep objects support __getitem__ but not dict.get(), and ACH responses
    # may omit AVS fields entirely.
    def _safe_get(key, default=''):
        try:
            value = resp[key]
        except (KeyError, AttributeError, TypeError):
            return default
        return default if value is None else value

    _card_code_map = {
        'M': 'Match',
        'N': 'No Match',
        'P': 'Not Processed',
        'S': 'Should be on card but not so indicated',
        'U': 'Issuer Not Certified',
        'X': 'No response from association',
        '': 'No CVV2/CVC data available for transaction',
    }
    card_code = _card_code_map.get(_safe_get('CardCodeResultCode', ''), '')
    avs = _safe_get('AvsResultCode', '')
    address, zip_code = 'No Match', 'No Match'
    if avs in ('YYY', 'Y', 'YYA', 'YYD', 'YYX', 'X', 'GGG', 'D'):
        address = zip_code = 'Match'
    elif avs in ('NYZ', 'Z', 'NYW', 'W', 'YGG', 'P'):
        zip_code = 'Match'
    elif avs in ('YNA', 'A', 'YNY', 'YYG', 'B', 'M'):
        address = 'Match'
    if address == 'No Match':
        address = _safe_get('AvsResult', address)
    if zip_code == 'No Match':
        zip_code = _safe_get('AvsResult', zip_code)
    return card_code.strip(), address.strip(), zip_code.strip()


def _year_selection_from_current():
    today = date.today()
    return [(str(y), str(y)) for y in range(today.year, today.year + 30)]


def _year_selection_from_2000():
    return [(str(y), str(y)) for y in range(2000, date.today().year + 30)]


def _month_selection():
    return [(str(i), str(i)) for i in range(1, 13)]


def _prepare_billing_address(record):
    partner_id = record.partner_id
    name_parts = partner_id.name.split(' ')
    address = ' '.join(filter(None, [partner_id.street, partner_id.street2]))
    return {
        "FirstName": name_parts[0],
        "LastName": ' '.join(name_parts[1:]),
        "CompanyName": partner_id.company_name if partner_id.company_name else '',
        "Address1": address,
        "City": partner_id.city if partner_id.city else '',
        "State": partner_id.state_id.code or 'CA',
        "ZipCode": partner_id.zip or '',
        "Country": partner_id.country_id.code or 'US',
    }

def _transaction_line(line):
    qty = line.product_uom_qty if hasattr(line, 'product_uom_qty') else line.quantity
    price_tax = line.price_tax if hasattr(line, 'price_tax') else 0
    return {
        'SKU': line.product_id.id,
        'ProductName': line.product_id.name,
        'Description': line.name,
        'UnitPrice': line.price_unit,
        'Taxable': bool(line.tax_ids),
        'TaxAmount': int(price_tax),
        'Qty': int(qty),
    }

def _transaction_lines(lines):
    return {'TransactionLineItem': [_transaction_line(line) for line in lines]}
