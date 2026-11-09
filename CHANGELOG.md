# Changelog

## [1.1.1](https://github.com/udondan/amazon-subscriptions/compare/v1.1.0...v1.1.1) (2026-11-09)


### Dependencies

* **deps:** replace amazon-orders with amazon-auth ([#52](https://github.com/udondan/amazon-subscriptions/issues/52)) ([6771e25](https://github.com/udondan/amazon-subscriptions/commit/6771e25d5584f4891139ae147f6f2352523dca62))
* **deps:** update dependency amazon-auth to v0.2.3 ([#57](https://github.com/udondan/amazon-subscriptions/issues/57)) ([8cac493](https://github.com/udondan/amazon-subscriptions/commit/8cac493c598e6b4cb96b9465a5b669b41f34ceb2))
* **deps:** update dependency click to v8.5.1 ([#53](https://github.com/udondan/amazon-subscriptions/issues/53)) ([3c01915](https://github.com/udondan/amazon-subscriptions/commit/3c01915265aee358258560be61471b4d8cd678e8))

## [1.1.0](https://github.com/udondan/amazon-subscriptions/compare/v1.0.1...v1.1.0) (2026-11-01)


### Features

* drop support for Python 3.10 ([#28](https://github.com/udondan/amazon-subscriptions/issues/28)) ([fb02fae](https://github.com/udondan/amazon-subscriptions/commit/fb02fae0056b17c39251f1c949449e22dfef5621))


### Bug Fixes

* **deps:** update certifi and pillow to patched versions ([#25](https://github.com/udondan/amazon-subscriptions/issues/25)) ([907956f](https://github.com/udondan/amazon-subscriptions/commit/907956f96158a162edc41abe1086d012823292b2))

## [1.0.1](https://github.com/udondan/amazon-subscriptions/compare/v1.0.0...v1.0.1) (2026-10-28)


### Documentation

* install from PyPI, where every release is published ([#22](https://github.com/udondan/amazon-subscriptions/issues/22)) ([f56bba4](https://github.com/udondan/amazon-subscriptions/commit/f56bba404a031c7476a8887f9b45e9c4448bebf7))

## [1.0.0](https://github.com/udondan/amazon-subscriptions/compare/v0.1.0...v1.0.0) (2026-10-28)


### ⚠ BREAKING CHANGES

* the English instead of the German pages are read, and the configured language package is ignored. The list price type "uvp" is now "rrp". amazon-orders comes from PyPI, version 5.2.0 or a later 5.x, which keeps the session of each site in its own file (e.g. cookies.amazon.de.json); a session stored in cookies.json is still used. Sites other than amazon.de are no longer rejected if they offer English.

### Features

* parse the English Subscribe & Save pages ([#20](https://github.com/udondan/amazon-subscriptions/issues/20)) ([f6361e4](https://github.com/udondan/amazon-subscriptions/commit/f6361e4fecd94247b5b4f13ad34ce57749251b94))

## 0.1.0 (2026-10-13)


### Features

* attribute product page prices to their offer and add list price type and alternative offer ([#5](https://github.com/udondan/amazon-subscriptions/issues/5)) ([07550d4](https://github.com/udondan/amazon-subscriptions/commit/07550d442b58ac87edddbb92bb5ff41bc0580a4d))
* read Subscribe & Save subscriptions and upcoming deliveries ([#1](https://github.com/udondan/amazon-subscriptions/issues/1)) ([0bdb700](https://github.com/udondan/amazon-subscriptions/commit/0bdb700d61ccac665897278de7c21d25a2697597))
* read the ASIN of backup products and, with --with-prices, regular, list and unit prices ([#3](https://github.com/udondan/amazon-subscriptions/issues/3)) ([22d96f0](https://github.com/udondan/amazon-subscriptions/commit/22d96f0a7e128b0a12a552e4ec974edf7816c9f9))


### Bug Fixes

* read the seller name of alternative offers from the offer row and add seller_id ([#6](https://github.com/udondan/amazon-subscriptions/issues/6)) ([0accfb9](https://github.com/udondan/amazon-subscriptions/commit/0accfb9d4ce017e0a3fe50e47d2d29d709fd1b38))
* return a partial result instead of failing when a delivery or product page cannot be read ([#7](https://github.com/udondan/amazon-subscriptions/issues/7)) ([3a3f08f](https://github.com/udondan/amazon-subscriptions/commit/3a3f08f8d797a0472b6add240c3ae454bb5755d2))
