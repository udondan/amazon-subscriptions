# Changelog

## [1.1.1](https://github.com/udondan/amazon-subscriptions/compare/v1.1.0...v1.1.1) (2026-11-07)


### Dependencies

* **deps:** lock file maintenance ([#39](https://github.com/udondan/amazon-subscriptions/issues/39)) ([eb41e0a](https://github.com/udondan/amazon-subscriptions/commit/eb41e0ac102f89fc51a9485c54bdbc1965858523))
* **deps:** update davidanson/markdownlint-cli2-action action to v25 ([#37](https://github.com/udondan/amazon-subscriptions/issues/37)) ([0509026](https://github.com/udondan/amazon-subscriptions/commit/0509026d4d28619c4fc22d1bb0f488f406a698f4))
* **deps:** update dependency amazon-orders to v5.2.1 ([#29](https://github.com/udondan/amazon-subscriptions/issues/29)) ([8721acd](https://github.com/udondan/amazon-subscriptions/commit/8721acd6376b1e17349afb4ab86fd8bf000f7853))
* **deps:** update dependency mypy to v2.4.1 ([#32](https://github.com/udondan/amazon-subscriptions/issues/32)) ([c2e8b67](https://github.com/udondan/amazon-subscriptions/commit/c2e8b67c08564efd0d3e5f149f2a055be7d45870))
* **deps:** update dependency pytest to v9.2.0 ([#33](https://github.com/udondan/amazon-subscriptions/issues/33)) ([1672bde](https://github.com/udondan/amazon-subscriptions/commit/1672bdef3cbf5caf3e3140acdbb83fe04a1b5414))
* **deps:** update dependency python to v3.15.2 ([#34](https://github.com/udondan/amazon-subscriptions/issues/34)) ([16dffc5](https://github.com/udondan/amazon-subscriptions/commit/16dffc5af67a6ecb2c7cdbe615bcbbc4314a760f))
* **deps:** update dependency ruff to v0.17.3 ([#35](https://github.com/udondan/amazon-subscriptions/issues/35)) ([4ef0450](https://github.com/udondan/amazon-subscriptions/commit/4ef0450bb97715995032f0eb2476edbfc2b3eb25))
* **deps:** update dependency types-requests to v2.33.0.20261030 ([#30](https://github.com/udondan/amazon-subscriptions/issues/30)) ([0b057d3](https://github.com/udondan/amazon-subscriptions/commit/0b057d309d9e505d48b97139433d2e0d1575d1d2))
* **deps:** update dependency uv to v0.13.7 ([#36](https://github.com/udondan/amazon-subscriptions/issues/36)) ([ab8b9bb](https://github.com/udondan/amazon-subscriptions/commit/ab8b9bbaddd7a972ec0c73d01a4d136ba5a3952f))
* **deps:** update jdx/mise-action action to v5 ([#38](https://github.com/udondan/amazon-subscriptions/issues/38)) ([6aecf1b](https://github.com/udondan/amazon-subscriptions/commit/6aecf1b34ab607f13a4034584d8d64bd80b37719))
* **deps:** update pypa/gh-action-pypi-publish action to v1.14.3 ([#31](https://github.com/udondan/amazon-subscriptions/issues/31)) ([b54c7eb](https://github.com/udondan/amazon-subscriptions/commit/b54c7eb24e5336a46608d9e536c5726e52b75278))


### Documentation

* add README badges ([#44](https://github.com/udondan/amazon-subscriptions/issues/44)) ([203f230](https://github.com/udondan/amazon-subscriptions/commit/203f230c11a52200dc12dd53245d93d29f97b8c9))

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


### Dependencies

* **deps:** update dependency ruff to v0.16.9 ([#9](https://github.com/udondan/amazon-subscriptions/issues/9)) ([ff25334](https://github.com/udondan/amazon-subscriptions/commit/ff25334c39d4e21857432ae0b9e83ddbfbcadf92))
