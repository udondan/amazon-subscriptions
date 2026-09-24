"""CSS selectors of the Subscribe & Save pages.

Classes with hashes (e.g. ``_myd-hub-..._style_tile__1pKIG``) change with every deployment, so only ids, ``data-``
attributes and stable class names are used.
"""

# Landing page (/auto-deliveries), and the fragments of its paginated subscriptions grid
SUBSCRIPTIONS_WIDGET = "[data-acp-path*='subscriptions-card']"
SUBSCRIPTIONS_GRID = "#subscriptionsDesktopGridLayout"
SUBSCRIPTION_TILE = "[data-edit-url*='subscriptionId=']"
SUBSCRIPTION_TILE_TITLE = ".a-truncate-full"
SUBSCRIPTION_TILE_IMAGE = "img"
SUBSCRIPTIONS_NEXT_PAGE = "[data-next-url*='/replenishment/subscriptions']"

DELIVERIES_WIDGET = "[data-acp-path*='deliveries-card']"
DELIVERY_CARD = ".hub-delivery-card"
DELIVERY_CARD_LINK = "a[href*='deliveryDate=']"
DELIVERY_CARD_IMAGE = "img"
DELIVERY_CARD_MORE_ITEMS = "[class*='plusCount']"
DELIVERIES_NEXT_PAGE = "[data-next-url*='/replenishment/fulfillment/deliveries']"

# Delivery page (/auto-deliveries/?deliveryDate=...)
DELIVERY_DATE = "[data-testid='ddp-atd-delivery-date']"
DELIVERY_EDIT_DEADLINE = "[data-testid='delivery-edit-deadline-date-desktop']"
DELIVERY_ITEM_COUNT = "[data-testid='delivery-item-count-desktop']"
DELIVERY_SAVINGS = "[data-testid='savings-celebration-desktop']"
DELIVERY_ITEM = "[data-testid='desktop-subscription-tile']"
DELIVERY_ITEM_TITLE = "[data-testid='product-title']"
DELIVERY_ITEM_QUANTITY_INTERVAL = "[data-testid='product-qty-frequency']"
DELIVERY_ITEM_PRICE = "[data-testid='product-price']"
DELIVERY_ITEM_DISCOUNT = "[data-testid='product-savings']"
DELIVERY_ITEM_ALERT = "[data-testid='subscription-item-alert']"

# Pages that are not the requested one
CAPTCHA = ["form[action*='validateCaptcha']", "#captchacharacters", "img[src*='/captcha/']"]
SIGN_IN = ["form[name='signIn']", "#ap_email", "#ap_password", "#auth-mfa-otpcode"]
