# Sentinel-Einzelpreis 999999 beim VenDoc-Export

Wenn Pricing Adjustments für ein Dokument aktiv sind (`apply_pricing_adjustments`),
exportieren wir bewusst `unit_price = 999999.0` (`PRICING_UNIT_PRICE_SENTINEL`)
statt des ursprünglichen Einzelpreises. Der maßgebliche Wert ist in diesem Fall
der Einkaufspreis in `purchase_price`; der auffällig unmögliche VK stellt sicher,
dass in VenDoc niemand versehentlich den Originalpreis als Verkaufspreis
übernimmt.

Diese Abweichung ist absichtlich und Teil des Export-Vertrags mit dem
VenDoc-Importer (siehe `docs/VENDOC_DRAGAN_HANDOVER.md`). Sie ist durch
`tests/test_export_contract.py` und die wertbasierten Tests in
`tests/test_vendoc_exporter.py` abgesichert — nicht „wegoptimieren".

Begriffe: siehe `CONTEXT.md` (Sentinel Unit Price, Purchase Price, Pricing Adjustments).
