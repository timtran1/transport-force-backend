import enum


class ConvertDirection(enum.Enum):
    send_to_receive = 'Send to Receive'
    receive_to_send = 'Receive to Send'


class FeeCharedTo(enum.Enum):
    sender = 'Sender'
    beneficiary = 'Beneficiary'


class ExchangeTransactionStatus(enum.Enum):
    draft = 'Draft'
    pending = 'Pending'
    processing = 'Processing'
    completed = 'Completed'
    failed = 'Failed'


class ExchangeAssetType(enum.Enum):
    crypto = 'Crypto'
    currency = 'Currency'


class ExchangeDelieveryMethod(enum.Enum):
    local = 'Via Local Bank'
    telegraphic = 'Via Telegraphic/Wire Transfer'


class PaymentTransferMethod(enum.Enum):
    cash = "Cash"
    local_bank_transfer = "Local bank transfer"
    telegraphic_transfer = "Telegraphic Transfer"