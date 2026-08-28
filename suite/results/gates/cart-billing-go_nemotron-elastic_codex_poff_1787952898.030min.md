# GATE — cart-billing-go_nemotron-elastic_codex_poff_1787952898 at 30 minutes

**How many of these 5 deliverables are COMPLETE?** Write the integer alone into `cart-billing-go_nemotron-elastic_codex_poff_1787952898.030min.verdict` in this directory. The run continues while you decide; it is stopped only if your answer is below 2.

Judge whether the work is DONE, not whether a check passes. A deliverable that works but trips a check on something incidental is complete. A deliverable that is written but cannot run is not.

## The deliverables this task names
1. rounding fixed + regression test
2. discounts.json with fallback
3. structured logging
4. behaviour preserved
5. third-party decimal money

## The task, as the coder received it
Fix the rounding bug causing totals to be one cent low. Example: three items at `19.99` with `SUMMER25` currently produce `48.57` instead of `48.58`. Add a regression test. 

Then, move discount codes from hard-coded values to a `discounts.json` file next to the binary. Put the current three codes in that file. If the file is missing, fall back to those same three codes. Stop using `float64` for money arithmetic. Add a third-party Go decimal module to `go.mod` and use it for cart calculations. Do not create a custom decimal type. Keep the `Item` struct field types unchanged; convert values inside the cart.

Log every computed total to `stderr` on one line, including the subtotal, discount code or `none`, and final total, so orders can be found with `grep`.

## What the repo's own verifier observes right now — EVIDENCE, not the verdict
- [NOT met] suite_green_plus_regression_test: 	go get cartsvc
- [NOT met] rounding_fixed_everywhere: reported cart totals imal/quantize (imported by cartsvc); to add:
	go get cartsvc (want 48.58); hidden cases: 	go get cartsvc
- [NOT met] discounts_from_file: discounts.json present, all three codes: True, still builds+passes without the file: False
- [NOT met] logging: stderr carried subtotal:False code:False total:False
- [met] decimal_money_library: declared ['github.com/govalues/decimal', 'github.com/govalues/decimal/quantize']; imported by non-test source: ['github.com/govalues/decimal', 'github.com/govalues/decimal/quantize']

## Everything the coder has changed since the seed
```diff
diff --git a/.cell-installs/xdg-cache/go-build/00/00353bf20941d042414adf6091e86aa5dc61935b5da1c16103721476864b61cb-a b/.cell-installs/xdg-cache/go-build/00/00353bf20941d042414adf6091e86aa5dc61935b5da1c16103721476864b61cb-a
new file mode 100644
index 0000000..bb5a1ab
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/00/00353bf20941d042414adf6091e86aa5dc61935b5da1c16103721476864b61cb-a
@@ -0,0 +1 @@
+v1 00353bf20941d042414adf6091e86aa5dc61935b5da1c16103721476864b61cb dc8ad309136b5d3a2c2b46978a599845afd59e29aa828f40b8df26262cc6df40                 2924  1787953170171159860
diff --git a/.cell-installs/xdg-cache/go-build/00/005069b27ad45a2a568c34cdb8cebafa3399119361c3424f57a9c962c5b95fee-a b/.cell-installs/xdg-cache/go-build/00/005069b27ad45a2a568c34cdb8cebafa3399119361c3424f57a9c962c5b95fee-a
new file mode 100644
index 0000000..eebbd09
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/00/005069b27ad45a2a568c34cdb8cebafa3399119361c3424f57a9c962c5b95fee-a
@@ -0,0 +1 @@
+v1 005069b27ad45a2a568c34cdb8cebafa3399119361c3424f57a9c962c5b95fee 10e62ccf7743df4fd0bc6c84ffecfdab71f66b329e05534b01603c2148c360d6               106250  1787953569989364170
diff --git a/.cell-installs/xdg-cache/go-build/00/009d834f5adda1179ff374e289a408b508796d05177b99fa92c55fddbf130440-d b/.cell-installs/xdg-cache/go-build/00/009d834f5adda1179ff374e289a408b508796d05177b99fa92c55fddbf130440-d
new file mode 100644
index 0000000..8bbb1b3
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/00/009d834f5adda1179ff374e289a408b508796d05177b99fa92c55fddbf130440-d differ
diff --git a/.cell-installs/xdg-cache/go-build/00/00d744abf0adb75984149e5aca81caf34bbca1529104ee36df2496b2552f1e6d-a b/.cell-installs/xdg-cache/go-build/00/00d744abf0adb75984149e5aca81caf34bbca1529104ee36df2496b2552f1e6d-a
new file mode 100644
index 0000000..eba8034
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/00/00d744abf0adb75984149e5aca81caf34bbca1529104ee36df2496b2552f1e6d-a
@@ -0,0 +1 @@
+v1 00d744abf0adb75984149e5aca81caf34bbca1529104ee36df2496b2552f1e6d a46209c72610b8c19afea6f3db163da6d44cd430f58800ba1377ed6ca2e62faf                 6063  1787953154052081337
diff --git a/.cell-installs/xdg-cache/go-build/00/00dedcbaf5dd36c49447863279d4bf0649eb1838d56074e8076fc688dff92fca-d b/.cell-installs/xdg-cache/go-build/00/00dedcbaf5dd36c49447863279d4bf0649eb1838d56074e8076fc688dff92fca-d
new file mode 100644
index 0000000..bdbf2c7
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/00/00dedcbaf5dd36c49447863279d4bf0649eb1838d56074e8076fc688dff92fca-d
@@ -0,0 +1 @@
+./godebug.go
diff --git a/.cell-installs/xdg-cache/go-build/00/00f0a7e2ff12704f102b32ad760a54c7d4e65cb9fece571313e8ca0e1af19711-a b/.cell-installs/xdg-cache/go-build/00/00f0a7e2ff12704f102b32ad760a54c7d4e65cb9fece571313e8ca0e1af19711-a
new file mode 100644
index 0000000..104b5dd
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/00/00f0a7e2ff12704f102b32ad760a54c7d4e65cb9fece571313e8ca0e1af19711-a
@@ -0,0 +1 @@
+v1 00f0a7e2ff12704f102b32ad760a54c7d4e65cb9fece571313e8ca0e1af19711 28043708092f509fa9134f4cdbca19d5cd6c87acefc6e7450a17482f328cf926                  129  1787953568890605285
diff --git a/.cell-installs/xdg-cache/go-build/01/011f0e0954b5932ba65169b3d515e3ae02701123de18c6c64da9b12566e8ac9b-a b/.cell-installs/xdg-cache/go-build/01/011f0e0954b5932ba65169b3d515e3ae02701123de18c6c64da9b12566e8ac9b-a
new file mode 100644
index 0000000..16980f8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/01/011f0e0954b5932ba65169b3d515e3ae02701123de18c6c64da9b12566e8ac9b-a
@@ -0,0 +1 @@
+v1 011f0e0954b5932ba65169b3d515e3ae02701123de18c6c64da9b12566e8ac9b e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569244714525
diff --git a/.cell-installs/xdg-cache/go-build/01/014373a58ab6393755b386ca68d613f301ed0481becdec50e22dfefff3ee1585-a b/.cell-installs/xdg-cache/go-build/01/014373a58ab6393755b386ca68d613f301ed0481becdec50e22dfefff3ee1585-a
new file mode 100644
index 0000000..2917ea2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/01/014373a58ab6393755b386ca68d613f301ed0481becdec50e22dfefff3ee1585-a
@@ -0,0 +1 @@
+v1 014373a58ab6393755b386ca68d613f301ed0481becdec50e22dfefff3ee1585 17fc0ffa711d99753502323c4abe3017b7f90ba36190e6b5357b7290af7f0e1f                 1546  1787953771567480907
diff --git a/.cell-installs/xdg-cache/go-build/02/02070e42c1af431f94a48e0e06995be6d1c2982d410b903ca17f7cd71f2287c2-d b/.cell-installs/xdg-cache/go-build/02/02070e42c1af431f94a48e0e06995be6d1c2982d410b903ca17f7cd71f2287c2-d
new file mode 100644
index 0000000..0c8c9c1
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/02/02070e42c1af431f94a48e0e06995be6d1c2982d410b903ca17f7cd71f2287c2-d differ
diff --git a/.cell-installs/xdg-cache/go-build/02/0228e8c8f89db1a322d617e46969cef886b9a0ebea8b462907df092f9339a73c-d b/.cell-installs/xdg-cache/go-build/02/0228e8c8f89db1a322d617e46969cef886b9a0ebea8b462907df092f9339a73c-d
new file mode 100644
index 0000000..d66f965
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/02/0228e8c8f89db1a322d617e46969cef886b9a0ebea8b462907df092f9339a73c-d differ
diff --git a/.cell-installs/xdg-cache/go-build/02/026ea4421214fcc424b21d42ac4a27aa52dcc9a54b0a628bf2df751e6f46bc81-d b/.cell-installs/xdg-cache/go-build/02/026ea4421214fcc424b21d42ac4a27aa52dcc9a54b0a628bf2df751e6f46bc81-d
new file mode 100644
index 0000000..720e347
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/02/026ea4421214fcc424b21d42ac4a27aa52dcc9a54b0a628bf2df751e6f46bc81-d
@@ -0,0 +1,10 @@
+./format.go
+./format_rfc3339.go
+./sleep.go
+./sys_unix.go
+./tick.go
+./time.go
+./zoneinfo.go
+./zoneinfo_goroot.go
+./zoneinfo_read.go
+./zoneinfo_unix.go
diff --git a/.cell-installs/xdg-cache/go-build/02/0294fd7d95a9819c480b6b6d44188a222c6b06d52dffb014ff0c606ddae5fb96-a b/.cell-installs/xdg-cache/go-build/02/0294fd7d95a9819c480b6b6d44188a222c6b06d52dffb014ff0c606ddae5fb96-a
new file mode 100644
index 0000000..caeefbe
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/02/0294fd7d95a9819c480b6b6d44188a222c6b06d52dffb014ff0c606ddae5fb96-a
@@ -0,0 +1 @@
+v1 0294fd7d95a9819c480b6b6d44188a222c6b06d52dffb014ff0c606ddae5fb96 f5b68ff0483990fe0c02f3a744232f500e56e02d88c5e728423282befaef0212                73542  1787953567806527844
diff --git a/.cell-installs/xdg-cache/go-build/02/02c77ed72cb8a7b421ee83af629e43dd4cd0106f76eb0d18af68c747e1c2fbcc-a b/.cell-installs/xdg-cache/go-build/02/02c77ed72cb8a7b421ee83af629e43dd4cd0106f76eb0d18af68c747e1c2fbcc-a
new file mode 100644
index 0000000..b94e087
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/02/02c77ed72cb8a7b421ee83af629e43dd4cd0106f76eb0d18af68c747e1c2fbcc-a
@@ -0,0 +1 @@
+v1 02c77ed72cb8a7b421ee83af629e43dd4cd0106f76eb0d18af68c747e1c2fbcc 026ea4421214fcc424b21d42ac4a27aa52dcc9a54b0a628bf2df751e6f46bc81                  150  1787953568975845342
diff --git a/.cell-installs/xdg-cache/go-build/03/030578bebf50a913f19157093b98cca797126399c6dfd1042e26db4d0aca8858-a b/.cell-installs/xdg-cache/go-build/03/030578bebf50a913f19157093b98cca797126399c6dfd1042e26db4d0aca8858-a
new file mode 100644
index 0000000..1a5528b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/03/030578bebf50a913f19157093b98cca797126399c6dfd1042e26db4d0aca8858-a
@@ -0,0 +1 @@
+v1 030578bebf50a913f19157093b98cca797126399c6dfd1042e26db4d0aca8858 18ba4eaab7c999ade8c650439eedd35138649d166fe6a5efafb0f231f47b1b0b                 1257  1787953153931354381
diff --git a/.cell-installs/xdg-cache/go-build/03/03459b1f612e068ee4ab63da5a6726072bf2342c5879da42a22eadf128096eb6-a b/.cell-installs/xdg-cache/go-build/03/03459b1f612e068ee4ab63da5a6726072bf2342c5879da42a22eadf128096eb6-a
new file mode 100644
index 0000000..fa5b072
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/03/03459b1f612e068ee4ab63da5a6726072bf2342c5879da42a22eadf128096eb6-a
@@ -0,0 +1 @@
+v1 03459b1f612e068ee4ab63da5a6726072bf2342c5879da42a22eadf128096eb6 86adbbb15c53775a99f62697b7e04b4648ccd5ae09c2ebf3916c7f1aa915148c                  535  1787953250754329693
diff --git a/.cell-installs/xdg-cache/go-build/03/03578691ec239e006f13e582606652319a58d2906f7ae3c75f92a8eb884f14b5-a b/.cell-installs/xdg-cache/go-build/03/03578691ec239e006f13e582606652319a58d2906f7ae3c75f92a8eb884f14b5-a
new file mode 100644
index 0000000..825347a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/03/03578691ec239e006f13e582606652319a58d2906f7ae3c75f92a8eb884f14b5-a
@@ -0,0 +1 @@
+v1 03578691ec239e006f13e582606652319a58d2906f7ae3c75f92a8eb884f14b5 e2a3a654f38558dd07ead8367e44fb55445c89bf000d6a2b1c7ec462384fa2bf                 5908  1787953153945769933
diff --git a/.cell-installs/xdg-cache/go-build/03/0378ae34f806f0822c157de519f5c3d795204b686b8bfcc1077a4f284c3dc83b-a b/.cell-installs/xdg-cache/go-build/03/0378ae34f806f0822c157de519f5c3d795204b686b8bfcc1077a4f284c3dc83b-a
new file mode 100644
index 0000000..f8dd3cd
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/03/0378ae34f806f0822c157de519f5c3d795204b686b8bfcc1077a4f284c3dc83b-a
@@ -0,0 +1 @@
+v1 0378ae34f806f0822c157de519f5c3d795204b686b8bfcc1077a4f284c3dc83b e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569320068045
diff --git a/.cell-installs/xdg-cache/go-build/03/0380c1cf4e9cad419a810f3ebdddb56bd5be331b4f8b2db916b5ce0ce7fe03f5-a b/.cell-installs/xdg-cache/go-build/03/0380c1cf4e9cad419a810f3ebdddb56bd5be331b4f8b2db916b5ce0ce7fe03f5-a
new file mode 100644
index 0000000..7721bae
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/03/0380c1cf4e9cad419a810f3ebdddb56bd5be331b4f8b2db916b5ce0ce7fe03f5-a
@@ -0,0 +1 @@
+v1 0380c1cf4e9cad419a810f3ebdddb56bd5be331b4f8b2db916b5ce0ce7fe03f5 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569876077194
diff --git a/.cell-installs/xdg-cache/go-build/03/039e540d210c4508b11acd3c2eb9d2bf5bdbe356f090b9adab973815d9096130-d b/.cell-installs/xdg-cache/go-build/03/039e540d210c4508b11acd3c2eb9d2bf5bdbe356f090b9adab973815d9096130-d
new file mode 100644
index 0000000..1aeff37
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/03/039e540d210c4508b11acd3c2eb9d2bf5bdbe356f090b9adab973815d9096130-d differ
diff --git a/.cell-installs/xdg-cache/go-build/03/03daaa7d05d0a2d9744a42bc21d6bdc779fa0ed254cbf79877d9d14b856cca62-d b/.cell-installs/xdg-cache/go-build/03/03daaa7d05d0a2d9744a42bc21d6bdc779fa0ed254cbf79877d9d14b856cca62-d
new file mode 100644
index 0000000..76f7fa4
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/03/03daaa7d05d0a2d9744a42bc21d6bdc779fa0ed254cbf79877d9d14b856cca62-d differ
diff --git a/.cell-installs/xdg-cache/go-build/04/0405921a145872a6254199260fd24bc9b36e46ce470b1e092591d9ac2a87670d-a b/.cell-installs/xdg-cache/go-build/04/0405921a145872a6254199260fd24bc9b36e46ce470b1e092591d9ac2a87670d-a
new file mode 100644
index 0000000..dbbed39
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/04/0405921a145872a6254199260fd24bc9b36e46ce470b1e092591d9ac2a87670d-a
@@ -0,0 +1 @@
+v1 0405921a145872a6254199260fd24bc9b36e46ce470b1e092591d9ac2a87670d e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570074747522
diff --git a/.cell-installs/xdg-cache/go-build/04/0409c44af377fa45588acc7ed9ebba366b07ef81e8604653a67bfc0c0ab98a66-a b/.cell-installs/xdg-cache/go-build/04/0409c44af377fa45588acc7ed9ebba366b07ef81e8604653a67bfc0c0ab98a66-a
new file mode 100644
index 0000000..5579001
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/04/0409c44af377fa45588acc7ed9ebba366b07ef81e8604653a67bfc0c0ab98a66-a
@@ -0,0 +1 @@
+v1 0409c44af377fa45588acc7ed9ebba366b07ef81e8604653a67bfc0c0ab98a66 f2564b56cb95242cf6165accdec3cd6a5b94824a67704933f42cf05dfb9c7bb1                 3566  1787953170166435826
diff --git a/.cell-installs/xdg-cache/go-build/04/0460b0e0383baa94ae790914f464e66e3da83e4f561ab4f096087ba1c930d2d5-a b/.cell-installs/xdg-cache/go-build/04/0460b0e0383baa94ae790914f464e66e3da83e4f561ab4f096087ba1c930d2d5-a
new file mode 100644
index 0000000..4125eef
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/04/0460b0e0383baa94ae790914f464e66e3da83e4f561ab4f096087ba1c930d2d5-a
@@ -0,0 +1 @@
+v1 0460b0e0383baa94ae790914f464e66e3da83e4f561ab4f096087ba1c930d2d5 47ecbdef62303d40929fb70a681e370c5cc16c3cb3e7486f00bd2ed3431f9520               551130  1787953569156637319
diff --git a/.cell-installs/xdg-cache/go-build/04/04b4509d27fd9c93eb33d9e8d80ff91f4a3bd31a7c7e2b9a77367d5c2f33aca8-d b/.cell-installs/xdg-cache/go-build/04/04b4509d27fd9c93eb33d9e8d80ff91f4a3bd31a7c7e2b9a77367d5c2f33aca8-d
new file mode 100644
index 0000000..3c50242
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/04/04b4509d27fd9c93eb33d9e8d80ff91f4a3bd31a7c7e2b9a77367d5c2f33aca8-d
@@ -0,0 +1,7 @@
+./deflate.go
+./deflatefast.go
+./dict_decoder.go
+./huffman_bit_writer.go
+./huffman_code.go
+./inflate.go
+./token.go
diff --git a/.cell-installs/xdg-cache/go-build/05/0510ebeaf8eedd20bf86a4b77bbcc32018d9ecffe9d9c924a32cb78bb42c2470-a b/.cell-installs/xdg-cache/go-build/05/0510ebeaf8eedd20bf86a4b77bbcc32018d9ecffe9d9c924a32cb78bb42c2470-a
new file mode 100644
index 0000000..32bfa1e
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/05/0510ebeaf8eedd20bf86a4b77bbcc32018d9ecffe9d9c924a32cb78bb42c2470-a
@@ -0,0 +1 @@
+v1 0510ebeaf8eedd20bf86a4b77bbcc32018d9ecffe9d9c924a32cb78bb42c2470 4a16a1243c9abc68554201809770c6af0942b4fd8c4c66ff112a129d27c0cfea                 3491  1787953154050085423
diff --git a/.cell-installs/xdg-cache/go-build/05/056dc392ff568679decf123aca9a89ef0d333de06a6ca767f4822fe24236535c-a b/.cell-installs/xdg-cache/go-build/05/056dc392ff568679decf123aca9a89ef0d333de06a6ca767f4822fe24236535c-a
new file mode 100644
index 0000000..9460d29
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/05/056dc392ff568679decf123aca9a89ef0d333de06a6ca767f4822fe24236535c-a
@@ -0,0 +1 @@
+v1 056dc392ff568679decf123aca9a89ef0d333de06a6ca767f4822fe24236535c 817d764c0c9369a93d7efcd16244d675859cf670a074c23e4b564a4810331878                13682  1787953567787013479
diff --git a/.cell-installs/xdg-cache/go-build/05/0582d6ba38f7786606e2db72f3ed1d3e143d5c4e3193004d31509a25ee1a30d1-a b/.cell-installs/xdg-cache/go-build/05/0582d6ba38f7786606e2db72f3ed1d3e143d5c4e3193004d31509a25ee1a30d1-a
new file mode 100644
index 0000000..142b255
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/05/0582d6ba38f7786606e2db72f3ed1d3e143d5c4e3193004d31509a25ee1a30d1-a
@@ -0,0 +1 @@
+v1 0582d6ba38f7786606e2db72f3ed1d3e143d5c4e3193004d31509a25ee1a30d1 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569912805750
diff --git a/.cell-installs/xdg-cache/go-build/05/0583c2fc2ec991b714507035e8b979859140d8a0c4fc5393133e4f1d824573eb-a b/.cell-installs/xdg-cache/go-build/05/0583c2fc2ec991b714507035e8b979859140d8a0c4fc5393133e4f1d824573eb-a
new file mode 100644
index 0000000..86cf11c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/05/0583c2fc2ec991b714507035e8b979859140d8a0c4fc5393133e4f1d824573eb-a
@@ -0,0 +1 @@
+v1 0583c2fc2ec991b714507035e8b979859140d8a0c4fc5393133e4f1d824573eb 9f158a54822707f7bb2cdabff2f8db3872ec00364728b330fcb3332cabc823ba                84354  1787953569322294433
diff --git a/.cell-installs/xdg-cache/go-build/05/059067f35f78410e458d26f0ed0b7c4e04e1f33bf394c455ac3b12438b11ce2b-d b/.cell-installs/xdg-cache/go-build/05/059067f35f78410e458d26f0ed0b7c4e04e1f33bf394c455ac3b12438b11ce2b-d
new file mode 100644
index 0000000..1b40ee7
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/05/059067f35f78410e458d26f0ed0b7c4e04e1f33bf394c455ac3b12438b11ce2b-d differ
diff --git a/.cell-installs/xdg-cache/go-build/05/05f5e6492430b00f807e4629c6e4a53f3948fc9382f19898d1cc361b3b99ff9b-d b/.cell-installs/xdg-cache/go-build/05/05f5e6492430b00f807e4629c6e4a53f3948fc9382f19898d1cc361b3b99ff9b-d
new file mode 100644
index 0000000..6e02bf9
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/05/05f5e6492430b00f807e4629c6e4a53f3948fc9382f19898d1cc361b3b99ff9b-d
@@ -0,0 +1,5 @@
+./doc.go
+./errors.go
+./format.go
+./print.go
+./scan.go
diff --git a/.cell-installs/xdg-cache/go-build/06/06387464faad8abe49c17449ae628c6bf28e4334bbfb565001f694a41935df02-a b/.cell-installs/xdg-cache/go-build/06/06387464faad8abe49c17449ae628c6bf28e4334bbfb565001f694a41935df02-a
new file mode 100644
index 0000000..616d14f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/06/06387464faad8abe49c17449ae628c6bf28e4334bbfb565001f694a41935df02-a
@@ -0,0 +1 @@
+v1 06387464faad8abe49c17449ae628c6bf28e4334bbfb565001f694a41935df02 872ebfa713f43f75af41cfac17d5055930ab7a0514597b6751bbded5c621168a                12890  1787953567792393900
diff --git a/.cell-installs/xdg-cache/go-build/06/06a45522df397b46b35bf32c99a6897f0e05a1628f940c5c48517ecab0a791ff-d b/.cell-installs/xdg-cache/go-build/06/06a45522df397b46b35bf32c99a6897f0e05a1628f940c5c48517ecab0a791ff-d
new file mode 100644
index 0000000..05310ce
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/06/06a45522df397b46b35bf32c99a6897f0e05a1628f940c5c48517ecab0a791ff-d
@@ -0,0 +1 @@
+./tabwriter.go
diff --git a/.cell-installs/xdg-cache/go-build/06/06b06f5d3ad757be70d3261c6ecd3f70745bd3ae269e73f742597ef7dfad5151-d b/.cell-installs/xdg-cache/go-build/06/06b06f5d3ad757be70d3261c6ecd3f70745bd3ae269e73f742597ef7dfad5151-d
new file mode 100644
index 0000000..ea28d56
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/06/06b06f5d3ad757be70d3261c6ecd3f70745bd3ae269e73f742597ef7dfad5151-d differ
diff --git a/.cell-installs/xdg-cache/go-build/06/06be03a136b1b5294de7e3fb288b69f5443780de9b8c2655e1b80e02b8a0084d-a b/.cell-installs/xdg-cache/go-build/06/06be03a136b1b5294de7e3fb288b69f5443780de9b8c2655e1b80e02b8a0084d-a
new file mode 100644
index 0000000..57ef454
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/06/06be03a136b1b5294de7e3fb288b69f5443780de9b8c2655e1b80e02b8a0084d-a
@@ -0,0 +1 @@
+v1 06be03a136b1b5294de7e3fb288b69f5443780de9b8c2655e1b80e02b8a0084d e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569916127072
diff --git a/.cell-installs/xdg-cache/go-build/07/07021552933f670e590c610c9108692ed55f3ac31156c84bcb41d78357d0a3ae-d b/.cell-installs/xdg-cache/go-build/07/07021552933f670e590c610c9108692ed55f3ac31156c84bcb41d78357d0a3ae-d
new file mode 100644
index 0000000..43e2bca
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/07/07021552933f670e590c610c9108692ed55f3ac31156c84bcb41d78357d0a3ae-d differ
diff --git a/.cell-installs/xdg-cache/go-build/07/076829fe7816678eced176c9a79582a1fb312baaa337bdf1a11e033b81e04222-d b/.cell-installs/xdg-cache/go-build/07/076829fe7816678eced176c9a79582a1fb312baaa337bdf1a11e033b81e04222-d
new file mode 100644
index 0000000..b023841
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/07/076829fe7816678eced176c9a79582a1fb312baaa337bdf1a11e033b81e04222-d differ
diff --git a/.cell-installs/xdg-cache/go-build/07/077c4c84129ee8b3bb95bdcaecd24bff550d8c7ecae971d146bf9590de7b41a9-d b/.cell-installs/xdg-cache/go-build/07/077c4c84129ee8b3bb95bdcaecd24bff550d8c7ecae971d146bf9590de7b41a9-d
new file mode 100644
index 0000000..56ef65c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/07/077c4c84129ee8b3bb95bdcaecd24bff550d8c7ecae971d146bf9590de7b41a9-d
@@ -0,0 +1 @@
+./crypto.go
diff --git a/.cell-installs/xdg-cache/go-build/07/07abd86d01b5a778b567fc49a8a06d9f80d9db944134cbb72177a19955f4a5a6-d b/.cell-installs/xdg-cache/go-build/07/07abd86d01b5a778b567fc49a8a06d9f80d9db944134cbb72177a19955f4a5a6-d
new file mode 100644
index 0000000..730814c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/07/07abd86d01b5a778b567fc49a8a06d9f80d9db944134cbb72177a19955f4a5a6-d
@@ -0,0 +1,2 @@
+./expr.go
+./vers.go
diff --git a/.cell-installs/xdg-cache/go-build/07/07bbc87352d64f3dc70dcb65edf40a6f39d8add91c1c9548af4bd26d28048b45-a b/.cell-installs/xdg-cache/go-build/07/07bbc87352d64f3dc70dcb65edf40a6f39d8add91c1c9548af4bd26d28048b45-a
new file mode 100644
index 0000000..675a559
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/07/07bbc87352d64f3dc70dcb65edf40a6f39d8add91c1c9548af4bd26d28048b45-a
@@ -0,0 +1 @@
+v1 07bbc87352d64f3dc70dcb65edf40a6f39d8add91c1c9548af4bd26d28048b45 9d3626929d20259d1c1fa1ef82f890d285b9b2582e0427e7472a329c66db8b5b                 3030  1787953771536381682
diff --git a/.cell-installs/xdg-cache/go-build/07/07cb3f3d1f21dfdea2b7a176908aae451761199416b5ad9fc524e8f534e97fe9-a b/.cell-installs/xdg-cache/go-build/07/07cb3f3d1f21dfdea2b7a176908aae451761199416b5ad9fc524e8f534e97fe9-a
new file mode 100644
index 0000000..0bb3e0b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/07/07cb3f3d1f21dfdea2b7a176908aae451761199416b5ad9fc524e8f534e97fe9-a
@@ -0,0 +1 @@
+v1 07cb3f3d1f21dfdea2b7a176908aae451761199416b5ad9fc524e8f534e97fe9 bc0213c21e48f877a9f5399cec35518623d7e908cb8d6f1ecb5055abfec40a40                  623  1787953153949925483
diff --git a/.cell-installs/xdg-cache/go-build/07/07e930387dfe725e539e4c4c77dbb51600b429492c1b6f9132bbf09e3feed43a-a b/.cell-installs/xdg-cache/go-build/07/07e930387dfe725e539e4c4c77dbb51600b429492c1b6f9132bbf09e3feed43a-a
new file mode 100644
index 0000000..b016492
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/07/07e930387dfe725e539e4c4c77dbb51600b429492c1b6f9132bbf09e3feed43a-a
@@ -0,0 +1 @@
+v1 07e930387dfe725e539e4c4c77dbb51600b429492c1b6f9132bbf09e3feed43a 6673f85d4ca930185ebdd741a615fbf0fc26494c8657c9574baa94a74d257549                   24  1787953569924468200
diff --git a/.cell-installs/xdg-cache/go-build/07/07f33fb36260e91afc5b2575d37440075dd2e4b93dde9b270b930bf78d2412fb-a b/.cell-installs/xdg-cache/go-build/07/07f33fb36260e91afc5b2575d37440075dd2e4b93dde9b270b930bf78d2412fb-a
new file mode 100644
index 0000000..272b116
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/07/07f33fb36260e91afc5b2575d37440075dd2e4b93dde9b270b930bf78d2412fb-a
@@ -0,0 +1 @@
+v1 07f33fb36260e91afc5b2575d37440075dd2e4b93dde9b270b930bf78d2412fb e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567787960517
diff --git a/.cell-installs/xdg-cache/go-build/08/087832261f11fa6e6fe4ec2160bd1580530b3ca62179bed9093beef47b6229f6-d b/.cell-installs/xdg-cache/go-build/08/087832261f11fa6e6fe4ec2160bd1580530b3ca62179bed9093beef47b6229f6-d
new file mode 100644
index 0000000..5bf8eed
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/08/087832261f11fa6e6fe4ec2160bd1580530b3ca62179bed9093beef47b6229f6-d differ
diff --git a/.cell-installs/xdg-cache/go-build/08/087971f9c035ac9abd6f075089cc0dc4553f468617a1d5a2f0bae86228064f7d-d b/.cell-installs/xdg-cache/go-build/08/087971f9c035ac9abd6f075089cc0dc4553f468617a1d5a2f0bae86228064f7d-d
new file mode 100644
index 0000000..bc831fa
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/08/087971f9c035ac9abd6f075089cc0dc4553f468617a1d5a2f0bae86228064f7d-d differ
diff --git a/.cell-installs/xdg-cache/go-build/08/08b010daca15e991836b3b37bf1f1be736e15ef6589870ec9f749556382e96e7-a b/.cell-installs/xdg-cache/go-build/08/08b010daca15e991836b3b37bf1f1be736e15ef6589870ec9f749556382e96e7-a
new file mode 100644
index 0000000..f731f12
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/08/08b010daca15e991836b3b37bf1f1be736e15ef6589870ec9f749556382e96e7-a
@@ -0,0 +1 @@
+v1 08b010daca15e991836b3b37bf1f1be736e15ef6589870ec9f749556382e96e7 812790363b4d2ed938a5e8885c30d111ef62d44b9ab49b20ec344a73cc3a34e8                 2275  1787953153935763175
diff --git a/.cell-installs/xdg-cache/go-build/08/08b5e0dab7d3087a33f63125a3e698d348aea5d157f099d2a4a331dccc410266-d b/.cell-installs/xdg-cache/go-build/08/08b5e0dab7d3087a33f63125a3e698d348aea5d157f099d2a4a331dccc410266-d
new file mode 100644
index 0000000..7ce7c70
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/08/08b5e0dab7d3087a33f63125a3e698d348aea5d157f099d2a4a331dccc410266-d
@@ -0,0 +1,8 @@
+./format.go
+./fs.go
+./glob.go
+./readdir.go
+./readfile.go
+./stat.go
+./sub.go
+./walk.go
diff --git a/.cell-installs/xdg-cache/go-build/08/08be81fa43a3e51b4af853e3a55949b014ac118991c6be9436bdf26683d34b8c-d b/.cell-installs/xdg-cache/go-build/08/08be81fa43a3e51b4af853e3a55949b014ac118991c6be9436bdf26683d34b8c-d
new file mode 100644
index 0000000..12a9927
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/08/08be81fa43a3e51b4af853e3a55949b014ac118991c6be9436bdf26683d34b8c-d differ
diff --git a/.cell-installs/xdg-cache/go-build/09/0901245aa2ed0867a2dbcb507efc23564178a09ad96c5209c37596355e811719-a b/.cell-installs/xdg-cache/go-build/09/0901245aa2ed0867a2dbcb507efc23564178a09ad96c5209c37596355e811719-a
new file mode 100644
index 0000000..3872c91
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/09/0901245aa2ed0867a2dbcb507efc23564178a09ad96c5209c37596355e811719-a
@@ -0,0 +1 @@
+v1 0901245aa2ed0867a2dbcb507efc23564178a09ad96c5209c37596355e811719 6a685cdba70dc2973550dae7daea6e4618d8b2e846e525dc9efb5114a2fd03cb                 2769  1787953170164628879
diff --git a/.cell-installs/xdg-cache/go-build/09/09726685b6b67c6715626167b6edcd9785517da9a9f411767d6000c40a8dfdb2-a b/.cell-installs/xdg-cache/go-build/09/09726685b6b67c6715626167b6edcd9785517da9a9f411767d6000c40a8dfdb2-a
new file mode 100644
index 0000000..d68663d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/09/09726685b6b67c6715626167b6edcd9785517da9a9f411767d6000c40a8dfdb2-a
@@ -0,0 +1 @@
+v1 09726685b6b67c6715626167b6edcd9785517da9a9f411767d6000c40a8dfdb2 087971f9c035ac9abd6f075089cc0dc4553f468617a1d5a2f0bae86228064f7d                59850  1787953568838632032
diff --git a/.cell-installs/xdg-cache/go-build/09/099945e6f8ec786e7bda5e805172384e3032b408ee117082b64d3c0b775ad578-a b/.cell-installs/xdg-cache/go-build/09/099945e6f8ec786e7bda5e805172384e3032b408ee117082b64d3c0b775ad578-a
new file mode 100644
index 0000000..97bcc5d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/09/099945e6f8ec786e7bda5e805172384e3032b408ee117082b64d3c0b775ad578-a
@@ -0,0 +1 @@
+v1 099945e6f8ec786e7bda5e805172384e3032b408ee117082b64d3c0b775ad578 6ac684b779dad008b4e8f57411749f7dfce5990a32b22f71db1c290070d0c1b5               825498  1787953569306702664
diff --git a/.cell-installs/xdg-cache/go-build/09/09a20b89423e3a400d3ec0fdc18f8f34f7cb35d23a13411f22986559be58dac5-a b/.cell-installs/xdg-cache/go-build/09/09a20b89423e3a400d3ec0fdc18f8f34f7cb35d23a13411f22986559be58dac5-a
new file mode 100644
index 0000000..6b826bc
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/09/09a20b89423e3a400d3ec0fdc18f8f34f7cb35d23a13411f22986559be58dac5-a
@@ -0,0 +1 @@
+v1 09a20b89423e3a400d3ec0fdc18f8f34f7cb35d23a13411f22986559be58dac5 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570251806824
diff --git a/.cell-installs/xdg-cache/go-build/0a/0a1c58563cdfc288b32d4896f8ac10962de34b1d3300ad3e304cb76055d04d1b-d b/.cell-installs/xdg-cache/go-build/0a/0a1c58563cdfc288b32d4896f8ac10962de34b1d3300ad3e304cb76055d04d1b-d
new file mode 100644
index 0000000..697d7c1
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/0a/0a1c58563cdfc288b32d4896f8ac10962de34b1d3300ad3e304cb76055d04d1b-d differ
diff --git a/.cell-installs/xdg-cache/go-build/0a/0a27c53faa2ef1aab911f3af7d46872a2603f41e95b621cf31adc34ed1674a89-a b/.cell-installs/xdg-cache/go-build/0a/0a27c53faa2ef1aab911f3af7d46872a2603f41e95b621cf31adc34ed1674a89-a
new file mode 100644
index 0000000..e009465
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0a/0a27c53faa2ef1aab911f3af7d46872a2603f41e95b621cf31adc34ed1674a89-a
@@ -0,0 +1 @@
+v1 0a27c53faa2ef1aab911f3af7d46872a2603f41e95b621cf31adc34ed1674a89 23eba1922a3055f8c1feff2a2d3b1dd616346789fb1052c90a79a03b07b3f4c0                20191  1787953771569426905
diff --git a/.cell-installs/xdg-cache/go-build/0a/0a3f8f994139ae0bb727f39aaee912e1a03229680c792351d15b4abd80b1819b-a b/.cell-installs/xdg-cache/go-build/0a/0a3f8f994139ae0bb727f39aaee912e1a03229680c792351d15b4abd80b1819b-a
new file mode 100644
index 0000000..7713198
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0a/0a3f8f994139ae0bb727f39aaee912e1a03229680c792351d15b4abd80b1819b-a
@@ -0,0 +1 @@
+v1 0a3f8f994139ae0bb727f39aaee912e1a03229680c792351d15b4abd80b1819b 70402071cfb27d1a2a4b79dd54dca59f811bf4f410636f06e2be349fddea172b                11122  1787953567787868469
diff --git a/.cell-installs/xdg-cache/go-build/0a/0a59dddfe062275f4906d756bead8b107f96ad88be242d57039ee88c6da30633-a b/.cell-installs/xdg-cache/go-build/0a/0a59dddfe062275f4906d756bead8b107f96ad88be242d57039ee88c6da30633-a
new file mode 100644
index 0000000..b84c5c0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0a/0a59dddfe062275f4906d756bead8b107f96ad88be242d57039ee88c6da30633-a
@@ -0,0 +1 @@
+v1 0a59dddfe062275f4906d756bead8b107f96ad88be242d57039ee88c6da30633 100b834209c1cb65f8f234ecde94f08c13dc468ee74a5d80bee2893c51ec586e                 1404  1787953153936586340
diff --git a/.cell-installs/xdg-cache/go-build/0a/0a7cba39df3c89b24f47344d6c302dda7f18e3b0a34d8dbbdf48d3187f7a076b-a b/.cell-installs/xdg-cache/go-build/0a/0a7cba39df3c89b24f47344d6c302dda7f18e3b0a34d8dbbdf48d3187f7a076b-a
new file mode 100644
index 0000000..de39f71
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0a/0a7cba39df3c89b24f47344d6c302dda7f18e3b0a34d8dbbdf48d3187f7a076b-a
@@ -0,0 +1 @@
+v1 0a7cba39df3c89b24f47344d6c302dda7f18e3b0a34d8dbbdf48d3187f7a076b 08be81fa43a3e51b4af853e3a55949b014ac118991c6be9436bdf26683d34b8c                 2323  1787953170158977175
diff --git a/.cell-installs/xdg-cache/go-build/0a/0a8dc72b0e1dccc292160ce5925aa7472e6c62897401228c4c383224f61b00ab-a b/.cell-installs/xdg-cache/go-build/0a/0a8dc72b0e1dccc292160ce5925aa7472e6c62897401228c4c383224f61b00ab-a
new file mode 100644
index 0000000..5782160
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0a/0a8dc72b0e1dccc292160ce5925aa7472e6c62897401228c4c383224f61b00ab-a
@@ -0,0 +1 @@
+v1 0a8dc72b0e1dccc292160ce5925aa7472e6c62897401228c4c383224f61b00ab e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567797645991
diff --git a/.cell-installs/xdg-cache/go-build/0a/0a8de68fdcbb95b62a6af8e8cb1a8b695d06af33619118b2c575e595c1132608-a b/.cell-installs/xdg-cache/go-build/0a/0a8de68fdcbb95b62a6af8e8cb1a8b695d06af33619118b2c575e595c1132608-a
new file mode 100644
index 0000000..b147b58
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0a/0a8de68fdcbb95b62a6af8e8cb1a8b695d06af33619118b2c575e595c1132608-a
@@ -0,0 +1 @@
+v1 0a8de68fdcbb95b62a6af8e8cb1a8b695d06af33619118b2c575e595c1132608 2925eb17eb658b53fc8bef7e9f751b972d8f9143b8391e7d7ee2079e2aa5f135                 2372  1787953170158787579
diff --git a/.cell-installs/xdg-cache/go-build/0a/0a9f7ce3238d841ca0edcb5100897026bcbded6f2cae78fd61c720c3be8eaa03-a b/.cell-installs/xdg-cache/go-build/0a/0a9f7ce3238d841ca0edcb5100897026bcbded6f2cae78fd61c720c3be8eaa03-a
new file mode 100644
index 0000000..7797ccb
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0a/0a9f7ce3238d841ca0edcb5100897026bcbded6f2cae78fd61c720c3be8eaa03-a
@@ -0,0 +1 @@
+v1 0a9f7ce3238d841ca0edcb5100897026bcbded6f2cae78fd61c720c3be8eaa03 2f5e7f599498786018f64342159d6fdde5671924d92d640ad9259829cdf7cd19                 5119  1787953170161178216
diff --git a/.cell-installs/xdg-cache/go-build/0a/0ade478c47682faf58a52859f6db10681be1a74a2410f86c57a51426afeac837-d b/.cell-installs/xdg-cache/go-build/0a/0ade478c47682faf58a52859f6db10681be1a74a2410f86c57a51426afeac837-d
new file mode 100644
index 0000000..38ce630
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/0a/0ade478c47682faf58a52859f6db10681be1a74a2410f86c57a51426afeac837-d differ
diff --git a/.cell-installs/xdg-cache/go-build/0b/0b02fd9cb6d44e7c17146cad24f16b1f9cf3c60f0f03a911b971a8001784575a-a b/.cell-installs/xdg-cache/go-build/0b/0b02fd9cb6d44e7c17146cad24f16b1f9cf3c60f0f03a911b971a8001784575a-a
new file mode 100644
index 0000000..9fe22dc
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0b/0b02fd9cb6d44e7c17146cad24f16b1f9cf3c60f0f03a911b971a8001784575a-a
@@ -0,0 +1 @@
+v1 0b02fd9cb6d44e7c17146cad24f16b1f9cf3c60f0f03a911b971a8001784575a 3a04d728de8df17525764461746ef224a07da074ed44c0039d2509975c5b29ca               170474  1787953568807876468
diff --git a/.cell-installs/xdg-cache/go-build/0b/0b2f8a77c6b0d955f19a5d49141af85cb110bcfb9436369724a11408a5ef56ec-a b/.cell-installs/xdg-cache/go-build/0b/0b2f8a77c6b0d955f19a5d49141af85cb110bcfb9436369724a11408a5ef56ec-a
new file mode 100644
index 0000000..f9951bd
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0b/0b2f8a77c6b0d955f19a5d49141af85cb110bcfb9436369724a11408a5ef56ec-a
@@ -0,0 +1 @@
+v1 0b2f8a77c6b0d955f19a5d49141af85cb110bcfb9436369724a11408a5ef56ec ddf370b7b78c5439c3c007e86546851555eaf739cc0160b4bc6686ac93d3e26a                   35  1787953568855678230
diff --git a/.cell-installs/xdg-cache/go-build/0b/0b47a1b62bbd2582c856a5fa62f0e91a2d89ca289dda1ba3074bc4783eea6555-d b/.cell-installs/xdg-cache/go-build/0b/0b47a1b62bbd2582c856a5fa62f0e91a2d89ca289dda1ba3074bc4783eea6555-d
new file mode 100644
index 0000000..f8e6d8a
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/0b/0b47a1b62bbd2582c856a5fa62f0e91a2d89ca289dda1ba3074bc4783eea6555-d differ
diff --git a/.cell-installs/xdg-cache/go-build/0b/0b7adac7bb198c25a9899c7684aeba4b1d80aa5ce7e5c14d142f6545fdc7d63a-a b/.cell-installs/xdg-cache/go-build/0b/0b7adac7bb198c25a9899c7684aeba4b1d80aa5ce7e5c14d142f6545fdc7d63a-a
new file mode 100644
index 0000000..12dae91
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0b/0b7adac7bb198c25a9899c7684aeba4b1d80aa5ce7e5c14d142f6545fdc7d63a-a
@@ -0,0 +1 @@
+v1 0b7adac7bb198c25a9899c7684aeba4b1d80aa5ce7e5c14d142f6545fdc7d63a e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567850248216
diff --git a/.cell-installs/xdg-cache/go-build/0b/0bc91248fe5a55ea12f7bcd19161508b2158c1b27dae0e9dc17a1723c7cd8188-a b/.cell-installs/xdg-cache/go-build/0b/0bc91248fe5a55ea12f7bcd19161508b2158c1b27dae0e9dc17a1723c7cd8188-a
new file mode 100644
index 0000000..9fb45b6
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0b/0bc91248fe5a55ea12f7bcd19161508b2158c1b27dae0e9dc17a1723c7cd8188-a
@@ -0,0 +1 @@
+v1 0bc91248fe5a55ea12f7bcd19161508b2158c1b27dae0e9dc17a1723c7cd8188 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567829608309
diff --git a/.cell-installs/xdg-cache/go-build/0b/0bfc0212057d6b5d46aef2b8595e8fcb387c535c99a2408ab592dee640458388-d b/.cell-installs/xdg-cache/go-build/0b/0bfc0212057d6b5d46aef2b8595e8fcb387c535c99a2408ab592dee640458388-d
new file mode 100644
index 0000000..5bfb45e
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/0b/0bfc0212057d6b5d46aef2b8595e8fcb387c535c99a2408ab592dee640458388-d differ
diff --git a/.cell-installs/xdg-cache/go-build/0c/0c0d2406829b5192ef4513ac501de781ccf483eb95fb76bfc7b5674a7c1170eb-d b/.cell-installs/xdg-cache/go-build/0c/0c0d2406829b5192ef4513ac501de781ccf483eb95fb76bfc7b5674a7c1170eb-d
new file mode 100644
index 0000000..9747531
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0c/0c0d2406829b5192ef4513ac501de781ccf483eb95fb76bfc7b5674a7c1170eb-d
@@ -0,0 +1 @@
+./hash.go
diff --git a/.cell-installs/xdg-cache/go-build/0c/0c506db8ed1ce5c4e2948b5960a088361841eb0f3c7a7a943244de9c93a0b91f-d b/.cell-installs/xdg-cache/go-build/0c/0c506db8ed1ce5c4e2948b5960a088361841eb0f3c7a7a943244de9c93a0b91f-d
new file mode 100644
index 0000000..84eca77
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/0c/0c506db8ed1ce5c4e2948b5960a088361841eb0f3c7a7a943244de9c93a0b91f-d differ
diff --git a/.cell-installs/xdg-cache/go-build/0c/0c6f5b0ae57581d106c1fdc1565c95a881c781a5d079895f896ecd3b6431382a-d b/.cell-installs/xdg-cache/go-build/0c/0c6f5b0ae57581d106c1fdc1565c95a881c781a5d079895f896ecd3b6431382a-d
new file mode 100644
index 0000000..1cc0c28
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/0c/0c6f5b0ae57581d106c1fdc1565c95a881c781a5d079895f896ecd3b6431382a-d differ
diff --git a/.cell-installs/xdg-cache/go-build/0c/0cadeac6ed13f8cc49b676a6ac3f7ba36796d22164af74986903971e5a3519b8-a b/.cell-installs/xdg-cache/go-build/0c/0cadeac6ed13f8cc49b676a6ac3f7ba36796d22164af74986903971e5a3519b8-a
new file mode 100644
index 0000000..541dcd4
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0c/0cadeac6ed13f8cc49b676a6ac3f7ba36796d22164af74986903971e5a3519b8-a
@@ -0,0 +1 @@
+v1 0cadeac6ed13f8cc49b676a6ac3f7ba36796d22164af74986903971e5a3519b8 ac3475974d44dc543d54e2b69e5fc678936c3b10900101ca40c58e531ae50e1f                 2264  1787953170166387896
diff --git a/.cell-installs/xdg-cache/go-build/0c/0cb5123eefb479665bcf7c4944caf150b763bd818e8ecdc98f14653d2acc5298-a b/.cell-installs/xdg-cache/go-build/0c/0cb5123eefb479665bcf7c4944caf150b763bd818e8ecdc98f14653d2acc5298-a
new file mode 100644
index 0000000..c1cce99
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0c/0cb5123eefb479665bcf7c4944caf150b763bd818e8ecdc98f14653d2acc5298-a
@@ -0,0 +1 @@
+v1 0cb5123eefb479665bcf7c4944caf150b763bd818e8ecdc98f14653d2acc5298 bf51ae08343dc40c3db503f273e704c290adcee3f05b8de71dad824acee0fdab                  578  1787953771534162613
diff --git a/.cell-installs/xdg-cache/go-build/0c/0ce1b1d60f8a08833d55ed93fc8ee8fb07397702e6958b03f6f4ba7b55cc006d-d b/.cell-installs/xdg-cache/go-build/0c/0ce1b1d60f8a08833d55ed93fc8ee8fb07397702e6958b03f6f4ba7b55cc006d-d
new file mode 100644
index 0000000..1d84fe4
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0c/0ce1b1d60f8a08833d55ed93fc8ee8fb07397702e6958b03f6f4ba7b55cc006d-d
@@ -0,0 +1 @@
+./table.go
diff --git a/.cell-installs/xdg-cache/go-build/0c/0ce6a71f2806e0faf4af2bf82f95e4c419914a9f26b0691d21c4100ee228682d-a b/.cell-installs/xdg-cache/go-build/0c/0ce6a71f2806e0faf4af2bf82f95e4c419914a9f26b0691d21c4100ee228682d-a
new file mode 100644
index 0000000..5d2cb29
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0c/0ce6a71f2806e0faf4af2bf82f95e4c419914a9f26b0691d21c4100ee228682d-a
@@ -0,0 +1 @@
+v1 0ce6a71f2806e0faf4af2bf82f95e4c419914a9f26b0691d21c4100ee228682d bf03044cba6f9374a04c3291b6ec70d6a33e7de8892c1b4a88e8cd194bd3c7a2               447662  1787953567851790743
diff --git a/.cell-installs/xdg-cache/go-build/0d/0d2a0ba6eb9379c5ff0e137bc928ea099d76e9f61d9c2a2c591cb2aef5922e46-d b/.cell-installs/xdg-cache/go-build/0d/0d2a0ba6eb9379c5ff0e137bc928ea099d76e9f61d9c2a2c591cb2aef5922e46-d
new file mode 100644
index 0000000..38f4dda
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/0d/0d2a0ba6eb9379c5ff0e137bc928ea099d76e9f61d9c2a2c591cb2aef5922e46-d differ
diff --git a/.cell-installs/xdg-cache/go-build/0d/0db54e86c270078bcaff4c9ed5b78148461ba555d1b2b7835cdfc6e41691cd1a-d b/.cell-installs/xdg-cache/go-build/0d/0db54e86c270078bcaff4c9ed5b78148461ba555d1b2b7835cdfc6e41691cd1a-d
new file mode 100644
index 0000000..4e1ff49
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/0d/0db54e86c270078bcaff4c9ed5b78148461ba555d1b2b7835cdfc6e41691cd1a-d differ
diff --git a/.cell-installs/xdg-cache/go-build/0e/0e113ea8bfe5f97b5c1004b223aade9d05fc7f19122dddeebe49d2ac8ba3e7ed-a b/.cell-installs/xdg-cache/go-build/0e/0e113ea8bfe5f97b5c1004b223aade9d05fc7f19122dddeebe49d2ac8ba3e7ed-a
new file mode 100644
index 0000000..2a22634
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0e/0e113ea8bfe5f97b5c1004b223aade9d05fc7f19122dddeebe49d2ac8ba3e7ed-a
@@ -0,0 +1 @@
+v1 0e113ea8bfe5f97b5c1004b223aade9d05fc7f19122dddeebe49d2ac8ba3e7ed c30c7406e98f2b98b3e0d2e9bdad052573865dd01ac197bbf000000e00d4f781                  219  1787953170191023616
diff --git a/.cell-installs/xdg-cache/go-build/0e/0eb9d1cd878cb95cd8f335f168972cb54e0b92121f4f052d3ab3c2d247409da0-a b/.cell-installs/xdg-cache/go-build/0e/0eb9d1cd878cb95cd8f335f168972cb54e0b92121f4f052d3ab3c2d247409da0-a
new file mode 100644
index 0000000..35ad40c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0e/0eb9d1cd878cb95cd8f335f168972cb54e0b92121f4f052d3ab3c2d247409da0-a
@@ -0,0 +1 @@
+v1 0eb9d1cd878cb95cd8f335f168972cb54e0b92121f4f052d3ab3c2d247409da0 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570213097556
diff --git a/.cell-installs/xdg-cache/go-build/0e/0ee1d66ba2d00b4346ab098cc4efe192aa29d3b3388dbbfdfc92eee1e5a6f6ee-a b/.cell-installs/xdg-cache/go-build/0e/0ee1d66ba2d00b4346ab098cc4efe192aa29d3b3388dbbfdfc92eee1e5a6f6ee-a
new file mode 100644
index 0000000..761d79f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0e/0ee1d66ba2d00b4346ab098cc4efe192aa29d3b3388dbbfdfc92eee1e5a6f6ee-a
@@ -0,0 +1 @@
+v1 0ee1d66ba2d00b4346ab098cc4efe192aa29d3b3388dbbfdfc92eee1e5a6f6ee e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570199927135
diff --git a/.cell-installs/xdg-cache/go-build/0f/0f3ef58f1b602e4d5ad4ec3be790193fb2c7eed4537b03197bd838099129e35f-a b/.cell-installs/xdg-cache/go-build/0f/0f3ef58f1b602e4d5ad4ec3be790193fb2c7eed4537b03197bd838099129e35f-a
new file mode 100644
index 0000000..26dd8fc
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0f/0f3ef58f1b602e4d5ad4ec3be790193fb2c7eed4537b03197bd838099129e35f-a
@@ -0,0 +1 @@
+v1 0f3ef58f1b602e4d5ad4ec3be790193fb2c7eed4537b03197bd838099129e35f e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569648246508
diff --git a/.cell-installs/xdg-cache/go-build/0f/0f57dbda1867ab405271f7a2b18db01bffe943f8f007122f0f9f13f5e7615bb6-d b/.cell-installs/xdg-cache/go-build/0f/0f57dbda1867ab405271f7a2b18db01bffe943f8f007122f0f9f13f5e7615bb6-d
new file mode 100644
index 0000000..4eeb9b6
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0f/0f57dbda1867ab405271f7a2b18db01bffe943f8f007122f0f9f13f5e7615bb6-d
@@ -0,0 +1,2 @@
+./exit.go
+./log.go
diff --git a/.cell-installs/xdg-cache/go-build/0f/0f680f68803a3caeaadbcca731acdceded5ff5744c2bb7e686a5bf5b3539746c-d b/.cell-installs/xdg-cache/go-build/0f/0f680f68803a3caeaadbcca731acdceded5ff5744c2bb7e686a5bf5b3539746c-d
new file mode 100644
index 0000000..316ae1e
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/0f/0f680f68803a3caeaadbcca731acdceded5ff5744c2bb7e686a5bf5b3539746c-d differ
diff --git a/.cell-installs/xdg-cache/go-build/0f/0f8693e97405a6b15dbe4b3bf10f0c2fe3b71cceef7660c4cf56f6978d7da5c2-d b/.cell-installs/xdg-cache/go-build/0f/0f8693e97405a6b15dbe4b3bf10f0c2fe3b71cceef7660c4cf56f6978d7da5c2-d
new file mode 100644
index 0000000..abe6e8b
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/0f/0f8693e97405a6b15dbe4b3bf10f0c2fe3b71cceef7660c4cf56f6978d7da5c2-d differ
diff --git a/.cell-installs/xdg-cache/go-build/0f/0fa01352f78279f622d11da018a2b2e3c0c97009ee95310fec3f3cda9e7d2b02-a b/.cell-installs/xdg-cache/go-build/0f/0fa01352f78279f622d11da018a2b2e3c0c97009ee95310fec3f3cda9e7d2b02-a
new file mode 100644
index 0000000..a6c3386
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0f/0fa01352f78279f622d11da018a2b2e3c0c97009ee95310fec3f3cda9e7d2b02-a
@@ -0,0 +1 @@
+v1 0fa01352f78279f622d11da018a2b2e3c0c97009ee95310fec3f3cda9e7d2b02 f545eea03c3b3918eb9ea8da640e4096bb88e737da8fe79b982282e391034a00                   50  1787953568824061773
diff --git a/.cell-installs/xdg-cache/go-build/0f/0fc4249800b0e4639d6e61b3498c1148d6c32d2e11c0ee4b3490574ae9003dc4-a b/.cell-installs/xdg-cache/go-build/0f/0fc4249800b0e4639d6e61b3498c1148d6c32d2e11c0ee4b3490574ae9003dc4-a
new file mode 100644
index 0000000..1f49176
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0f/0fc4249800b0e4639d6e61b3498c1148d6c32d2e11c0ee4b3490574ae9003dc4-a
@@ -0,0 +1 @@
+v1 0fc4249800b0e4639d6e61b3498c1148d6c32d2e11c0ee4b3490574ae9003dc4 0c506db8ed1ce5c4e2948b5960a088361841eb0f3c7a7a943244de9c93a0b91f              1153052  1787953570184198412
diff --git a/.cell-installs/xdg-cache/go-build/0f/0ffb0e6c357746e69605b88a2e5fbbf12155129e78f6a8232224792c6f15a4d4-a b/.cell-installs/xdg-cache/go-build/0f/0ffb0e6c357746e69605b88a2e5fbbf12155129e78f6a8232224792c6f15a4d4-a
new file mode 100644
index 0000000..4c9eb9c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/0f/0ffb0e6c357746e69605b88a2e5fbbf12155129e78f6a8232224792c6f15a4d4-a
@@ -0,0 +1 @@
+v1 0ffb0e6c357746e69605b88a2e5fbbf12155129e78f6a8232224792c6f15a4d4 3649ca91c28b67786b59130a587e9059fd5c785dfd72228690287b55185a25df                   16  1787953570067769079
diff --git a/.cell-installs/xdg-cache/go-build/10/1001cbf856a1abdcb79d01aa0bb7c8a9dc9dcb85371c9f364ce792e77d216427-a b/.cell-installs/xdg-cache/go-build/10/1001cbf856a1abdcb79d01aa0bb7c8a9dc9dcb85371c9f364ce792e77d216427-a
new file mode 100644
index 0000000..fe806ea
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/10/1001cbf856a1abdcb79d01aa0bb7c8a9dc9dcb85371c9f364ce792e77d216427-a
@@ -0,0 +1 @@
+v1 1001cbf856a1abdcb79d01aa0bb7c8a9dc9dcb85371c9f364ce792e77d216427 ff70a867d3d551b76c3e8ac051bb675ebf0a2edef07d582cfc3e58c14047b111                 1730  1787953170168617540
diff --git a/.cell-installs/xdg-cache/go-build/10/100b834209c1cb65f8f234ecde94f08c13dc468ee74a5d80bee2893c51ec586e-d b/.cell-installs/xdg-cache/go-build/10/100b834209c1cb65f8f234ecde94f08c13dc468ee74a5d80bee2893c51ec586e-d
new file mode 100644
index 0000000..412104e
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/10/100b834209c1cb65f8f234ecde94f08c13dc468ee74a5d80bee2893c51ec586e-d differ
diff --git a/.cell-installs/xdg-cache/go-build/10/102eaf00a9ec00a6101b9ed000d16f694716a38617fc5395dfd5a55cc941f975-a b/.cell-installs/xdg-cache/go-build/10/102eaf00a9ec00a6101b9ed000d16f694716a38617fc5395dfd5a55cc941f975-a
new file mode 100644
index 0000000..8a4cf53
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/10/102eaf00a9ec00a6101b9ed000d16f694716a38617fc5395dfd5a55cc941f975-a
@@ -0,0 +1 @@
+v1 102eaf00a9ec00a6101b9ed000d16f694716a38617fc5395dfd5a55cc941f975 14553726da5f044d7f63cf104baa439d5e8f3d93c2774b840dc728771e6fee94                  597  1787953170153221531
diff --git a/.cell-installs/xdg-cache/go-build/10/104702ac22f0c564f700f00c6487283866ecece0443ea799bdcc1d5355d9115e-d b/.cell-installs/xdg-cache/go-build/10/104702ac22f0c564f700f00c6487283866ecece0443ea799bdcc1d5355d9115e-d
new file mode 100644
index 0000000..12139cd
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/10/104702ac22f0c564f700f00c6487283866ecece0443ea799bdcc1d5355d9115e-d differ
diff --git a/.cell-installs/xdg-cache/go-build/10/10932f0d39ecaea57a57a58352ad7a39482ca0a5bd8a518ab2f4bfc1c6a2e55a-a b/.cell-installs/xdg-cache/go-build/10/10932f0d39ecaea57a57a58352ad7a39482ca0a5bd8a518ab2f4bfc1c6a2e55a-a
new file mode 100644
index 0000000..dc753eb
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/10/10932f0d39ecaea57a57a58352ad7a39482ca0a5bd8a518ab2f4bfc1c6a2e55a-a
@@ -0,0 +1 @@
+v1 10932f0d39ecaea57a57a58352ad7a39482ca0a5bd8a518ab2f4bfc1c6a2e55a 67746ad597832bc4b47103cbe0d0fd90e2091657ee4948607b31bc9c4f1cbfd1                   21  1787953568907527583
diff --git a/.cell-installs/xdg-cache/go-build/10/10b0709935bbdb5a308b97bf016d1e23cff5cf54085cee4ba61fdba366ee9a09-d b/.cell-installs/xdg-cache/go-build/10/10b0709935bbdb5a308b97bf016d1e23cff5cf54085cee4ba61fdba366ee9a09-d
new file mode 100644
index 0000000..45ce5f0
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/10/10b0709935bbdb5a308b97bf016d1e23cff5cf54085cee4ba61fdba366ee9a09-d differ
diff --git a/.cell-installs/xdg-cache/go-build/10/10bebc44135627dd29603f297df7d9fc85dbbfc0ce848c7565487a499213d0b6-a b/.cell-installs/xdg-cache/go-build/10/10bebc44135627dd29603f297df7d9fc85dbbfc0ce848c7565487a499213d0b6-a
new file mode 100644
index 0000000..80f225a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/10/10bebc44135627dd29603f297df7d9fc85dbbfc0ce848c7565487a499213d0b6-a
@@ -0,0 +1 @@
+v1 10bebc44135627dd29603f297df7d9fc85dbbfc0ce848c7565487a499213d0b6 3a2247463477d7161e05902eae24cac571de58aeebaebc346c2861e077ee233c                    9  1787953567781540897
diff --git a/.cell-installs/xdg-cache/go-build/10/10e24fff786f1cf9fb8a0981a91cd92a9fa5f8a10819497275cc7f20e7e11748-a b/.cell-installs/xdg-cache/go-build/10/10e24fff786f1cf9fb8a0981a91cd92a9fa5f8a10819497275cc7f20e7e11748-a
new file mode 100644
index 0000000..18b7a81
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/10/10e24fff786f1cf9fb8a0981a91cd92a9fa5f8a10819497275cc7f20e7e11748-a
@@ -0,0 +1 @@
+v1 10e24fff786f1cf9fb8a0981a91cd92a9fa5f8a10819497275cc7f20e7e11748 36c8d9a054c6c3885b6865bbf913a9de6e4f4ae3ebd043f781880eaa616aa598                  878  1787953170164882367
diff --git a/.cell-installs/xdg-cache/go-build/10/10e62ccf7743df4fd0bc6c84ffecfdab71f66b329e05534b01603c2148c360d6-d b/.cell-installs/xdg-cache/go-build/10/10e62ccf7743df4fd0bc6c84ffecfdab71f66b329e05534b01603c2148c360d6-d
new file mode 100644
index 0000000..a3658a8
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/10/10e62ccf7743df4fd0bc6c84ffecfdab71f66b329e05534b01603c2148c360d6-d differ
diff --git a/.cell-installs/xdg-cache/go-build/11/117f153b58c617ef30fb6daddc0c7010209ccf5ba8171c100dec74b2f543722c-a b/.cell-installs/xdg-cache/go-build/11/117f153b58c617ef30fb6daddc0c7010209ccf5ba8171c100dec74b2f543722c-a
new file mode 100644
index 0000000..3c16964
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/11/117f153b58c617ef30fb6daddc0c7010209ccf5ba8171c100dec74b2f543722c-a
@@ -0,0 +1 @@
+v1 117f153b58c617ef30fb6daddc0c7010209ccf5ba8171c100dec74b2f543722c 196bcb8298ec68e9fd730bcd530179198ad0bb5a00c940141fb400f951b3cdc8                  571  1787954143951981448
diff --git a/.cell-installs/xdg-cache/go-build/12/1278ae5aa98ae1693aa315ef8adc6ed50d8f7cd7878788f3dfa33011999d152f-d b/.cell-installs/xdg-cache/go-build/12/1278ae5aa98ae1693aa315ef8adc6ed50d8f7cd7878788f3dfa33011999d152f-d
new file mode 100644
index 0000000..fc2c14d
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/12/1278ae5aa98ae1693aa315ef8adc6ed50d8f7cd7878788f3dfa33011999d152f-d differ
diff --git a/.cell-installs/xdg-cache/go-build/12/12d28680522f553477a34c5a6542d7d0bdef408978f35aec90e2b5748de2c200-a b/.cell-installs/xdg-cache/go-build/12/12d28680522f553477a34c5a6542d7d0bdef408978f35aec90e2b5748de2c200-a
new file mode 100644
index 0000000..9c829b3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/12/12d28680522f553477a34c5a6542d7d0bdef408978f35aec90e2b5748de2c200-a
@@ -0,0 +1 @@
+v1 12d28680522f553477a34c5a6542d7d0bdef408978f35aec90e2b5748de2c200 aedfb205c0bb730af484b88b0d06903cbbfe5d3734da2a968bd4c52637596f5b                 2245  1787953771569930039
diff --git a/.cell-installs/xdg-cache/go-build/13/132645e69702a38b40a3d04333dc2f3261cddb5ab6092f9e1cd6077181447049-d b/.cell-installs/xdg-cache/go-build/13/132645e69702a38b40a3d04333dc2f3261cddb5ab6092f9e1cd6077181447049-d
new file mode 100644
index 0000000..9de568b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/13/132645e69702a38b40a3d04333dc2f3261cddb5ab6092f9e1cd6077181447049-d
@@ -0,0 +1,2 @@
+./path.go
+./path_other.go
diff --git a/.cell-installs/xdg-cache/go-build/13/1334a3ef9f28e14c69627e58ca30baec55feb082c1e96dafb89b192d2403c5de-a b/.cell-installs/xdg-cache/go-build/13/1334a3ef9f28e14c69627e58ca30baec55feb082c1e96dafb89b192d2403c5de-a
new file mode 100644
index 0000000..aa9beee
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/13/1334a3ef9f28e14c69627e58ca30baec55feb082c1e96dafb89b192d2403c5de-a
@@ -0,0 +1 @@
+v1 1334a3ef9f28e14c69627e58ca30baec55feb082c1e96dafb89b192d2403c5de cdeac5984c1defe3f74ba3a7dd9384a3ebd04d96a1f0be639b6aed4bd434d478                 2308  1787953170148142846
diff --git a/.cell-installs/xdg-cache/go-build/13/1357a859103dc38781f79d277f194e53fce4ffbea054d6543af474d52e5a3d5e-d b/.cell-installs/xdg-cache/go-build/13/1357a859103dc38781f79d277f194e53fce4ffbea054d6543af474d52e5a3d5e-d
new file mode 100644
index 0000000..492402b
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/13/1357a859103dc38781f79d277f194e53fce4ffbea054d6543af474d52e5a3d5e-d differ
diff --git a/.cell-installs/xdg-cache/go-build/13/135ec64efa95003d70424891f075c1dfdb3235c07274852c2a812e31db5a7d7b-a b/.cell-installs/xdg-cache/go-build/13/135ec64efa95003d70424891f075c1dfdb3235c07274852c2a812e31db5a7d7b-a
new file mode 100644
index 0000000..ee39510
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/13/135ec64efa95003d70424891f075c1dfdb3235c07274852c2a812e31db5a7d7b-a
@@ -0,0 +1 @@
+v1 135ec64efa95003d70424891f075c1dfdb3235c07274852c2a812e31db5a7d7b 1e7fedeebd58b5919f66a39e98ffc789cb9563a540b61106d74323e585f6075b                 3392  1787953170167128863
diff --git a/.cell-installs/xdg-cache/go-build/13/13ba98b65e839b289e068cbe0886b2e95e27a5814d0b2e4bfbad8fc3aa1e0ce0-a b/.cell-installs/xdg-cache/go-build/13/13ba98b65e839b289e068cbe0886b2e95e27a5814d0b2e4bfbad8fc3aa1e0ce0-a
new file mode 100644
index 0000000..4779124
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/13/13ba98b65e839b289e068cbe0886b2e95e27a5814d0b2e4bfbad8fc3aa1e0ce0-a
@@ -0,0 +1 @@
+v1 13ba98b65e839b289e068cbe0886b2e95e27a5814d0b2e4bfbad8fc3aa1e0ce0 1e1cab71c7ec26658dc2da9a9e51a78ac604a06e74e4d3f1c69d49c1a11be6d5                  133  1787953569613535899
diff --git a/.cell-installs/xdg-cache/go-build/13/13ff642a7b1b7cb2e3cc1797bd3b141a03926c101408674befef2945a0e276d9-d b/.cell-installs/xdg-cache/go-build/13/13ff642a7b1b7cb2e3cc1797bd3b141a03926c101408674befef2945a0e276d9-d
new file mode 100644
index 0000000..a846c0e
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/13/13ff642a7b1b7cb2e3cc1797bd3b141a03926c101408674befef2945a0e276d9-d differ
diff --git a/.cell-installs/xdg-cache/go-build/14/14553726da5f044d7f63cf104baa439d5e8f3d93c2774b840dc728771e6fee94-d b/.cell-installs/xdg-cache/go-build/14/14553726da5f044d7f63cf104baa439d5e8f3d93c2774b840dc728771e6fee94-d
new file mode 100644
index 0000000..2f97315
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/14/14553726da5f044d7f63cf104baa439d5e8f3d93c2774b840dc728771e6fee94-d differ
diff --git a/.cell-installs/xdg-cache/go-build/15/151233c7aa22f7c263dd4a9ac8a7cfc011c58408ec49f3cfcdb8c3d33f325895-a b/.cell-installs/xdg-cache/go-build/15/151233c7aa22f7c263dd4a9ac8a7cfc011c58408ec49f3cfcdb8c3d33f325895-a
new file mode 100644
index 0000000..5393748
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/15/151233c7aa22f7c263dd4a9ac8a7cfc011c58408ec49f3cfcdb8c3d33f325895-a
@@ -0,0 +1 @@
+v1 151233c7aa22f7c263dd4a9ac8a7cfc011c58408ec49f3cfcdb8c3d33f325895 02070e42c1af431f94a48e0e06995be6d1c2982d410b903ca17f7cd71f2287c2                 3041  1787953771531000010
diff --git a/.cell-installs/xdg-cache/go-build/15/151ddd9cb51a79d07510a614410b29478a3ed421b4c4779c1072358e665111f5-a b/.cell-installs/xdg-cache/go-build/15/151ddd9cb51a79d07510a614410b29478a3ed421b4c4779c1072358e665111f5-a
new file mode 100644
index 0000000..0d5ff7d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/15/151ddd9cb51a79d07510a614410b29478a3ed421b4c4779c1072358e665111f5-a
@@ -0,0 +1 @@
+v1 151ddd9cb51a79d07510a614410b29478a3ed421b4c4779c1072358e665111f5 6108a65a8a22a4978cd3c1f7d61f73a2944db05d66c5410e550498023ca203fd                   21  1787953568975494840
diff --git a/.cell-installs/xdg-cache/go-build/15/1573a9c19a35a64abc0e6e692739fa4980d744a6f28348cc23588bd4c9544001-a b/.cell-installs/xdg-cache/go-build/15/1573a9c19a35a64abc0e6e692739fa4980d744a6f28348cc23588bd4c9544001-a
new file mode 100644
index 0000000..9bb45bc
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/15/1573a9c19a35a64abc0e6e692739fa4980d744a6f28348cc23588bd4c9544001-a
@@ -0,0 +1 @@
+v1 1573a9c19a35a64abc0e6e692739fa4980d744a6f28348cc23588bd4c9544001 b6cef41ae7333442ba4eaaf997c886e7af00d9fd3a1540abee88cd327f23378b                43284  1787953568796112444
diff --git a/.cell-installs/xdg-cache/go-build/15/15de9126f3209e85edd02cf45ce0752b960fa99c8e27ab8184293245f5d35b0e-a b/.cell-installs/xdg-cache/go-build/15/15de9126f3209e85edd02cf45ce0752b960fa99c8e27ab8184293245f5d35b0e-a
new file mode 100644
index 0000000..20e5995
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/15/15de9126f3209e85edd02cf45ce0752b960fa99c8e27ab8184293245f5d35b0e-a
@@ -0,0 +1 @@
+v1 15de9126f3209e85edd02cf45ce0752b960fa99c8e27ab8184293245f5d35b0e e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569917907409
diff --git a/.cell-installs/xdg-cache/go-build/16/16005e6e26c0f80a2c9879a4f8958dbae74e47f9cdd059fa10b49c43ddb35771-a b/.cell-installs/xdg-cache/go-build/16/16005e6e26c0f80a2c9879a4f8958dbae74e47f9cdd059fa10b49c43ddb35771-a
new file mode 100644
index 0000000..b0003c5
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/16/16005e6e26c0f80a2c9879a4f8958dbae74e47f9cdd059fa10b49c43ddb35771-a
@@ -0,0 +1 @@
+v1 16005e6e26c0f80a2c9879a4f8958dbae74e47f9cdd059fa10b49c43ddb35771 27df7d09a33d50318585c6263ade499035c74922e59a5f1f3422ffdd2c3bd3be                  424  1787953771565098258
diff --git a/.cell-installs/xdg-cache/go-build/17/1722e39b2eec812fae3b211d6e60f4a433f0d07a5be681d4de36532e00aac03c-d b/.cell-installs/xdg-cache/go-build/17/1722e39b2eec812fae3b211d6e60f4a433f0d07a5be681d4de36532e00aac03c-d
new file mode 100644
index 0000000..17d5ea0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/17/1722e39b2eec812fae3b211d6e60f4a433f0d07a5be681d4de36532e00aac03c-d
@@ -0,0 +1,2 @@
+./doc.go
+./norace.go
diff --git a/.cell-installs/xdg-cache/go-build/17/174ed9c6ef5fc265c5b0ac77199c1f16fdcf46d654e6249ed057c4921ad01947-a b/.cell-installs/xdg-cache/go-build/17/174ed9c6ef5fc265c5b0ac77199c1f16fdcf46d654e6249ed057c4921ad01947-a
new file mode 100644
index 0000000..6bebbcd
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/17/174ed9c6ef5fc265c5b0ac77199c1f16fdcf46d654e6249ed057c4921ad01947-a
@@ -0,0 +1 @@
+v1 174ed9c6ef5fc265c5b0ac77199c1f16fdcf46d654e6249ed057c4921ad01947 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953919161793122
diff --git a/.cell-installs/xdg-cache/go-build/17/17527eee5829ad779e760855927a55219f49637e044551928756aaf412571fda-d b/.cell-installs/xdg-cache/go-build/17/17527eee5829ad779e760855927a55219f49637e044551928756aaf412571fda-d
new file mode 100644
index 0000000..b2e9aa6
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/17/17527eee5829ad779e760855927a55219f49637e044551928756aaf412571fda-d differ
diff --git a/.cell-installs/xdg-cache/go-build/17/17a678fa7e0d1624a6c02dd3ded8901328144219dbbc15abaf150fec4c173d6b-d b/.cell-installs/xdg-cache/go-build/17/17a678fa7e0d1624a6c02dd3ded8901328144219dbbc15abaf150fec4c173d6b-d
new file mode 100644
index 0000000..7d17d44
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/17/17a678fa7e0d1624a6c02dd3ded8901328144219dbbc15abaf150fec4c173d6b-d
@@ -0,0 +1,3 @@
+./goarch.go
+./goarch_amd64.go
+./zgoarch_amd64.go
diff --git a/.cell-installs/xdg-cache/go-build/17/17abede116707cbbd6d9b6fff561313d1d8010285013c1b1d60e3b9004ca7f45-a b/.cell-installs/xdg-cache/go-build/17/17abede116707cbbd6d9b6fff561313d1d8010285013c1b1d60e3b9004ca7f45-a
new file mode 100644
index 0000000..b771232
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/17/17abede116707cbbd6d9b6fff561313d1d8010285013c1b1d60e3b9004ca7f45-a
@@ -0,0 +1 @@
+v1 17abede116707cbbd6d9b6fff561313d1d8010285013c1b1d60e3b9004ca7f45 76a190657ccd0db4615b611531fbb450d13fbb39c0fbe2bc7fbedf902686667d                   10  1787953569309962363
diff --git a/.cell-installs/xdg-cache/go-build/17/17ad6cd190841daa9a34867120b5bc58e68c3df38dd042cf9bb1949937e9aee3-a b/.cell-installs/xdg-cache/go-build/17/17ad6cd190841daa9a34867120b5bc58e68c3df38dd042cf9bb1949937e9aee3-a
new file mode 100644
index 0000000..8291608
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/17/17ad6cd190841daa9a34867120b5bc58e68c3df38dd042cf9bb1949937e9aee3-a
@@ -0,0 +1 @@
+v1 17ad6cd190841daa9a34867120b5bc58e68c3df38dd042cf9bb1949937e9aee3 2e784afac11430a60db4f73a57bf6a31592eb7558eb6ce8a16e4a204ad4c3fac                  584  1787953153936588788
diff --git a/.cell-installs/xdg-cache/go-build/17/17ef644b8d43e32bc29577da07d4c49871b7dedfdc411bedc6f90ca66b6bae45-a b/.cell-installs/xdg-cache/go-build/17/17ef644b8d43e32bc29577da07d4c49871b7dedfdc411bedc6f90ca66b6bae45-a
new file mode 100644
index 0000000..e90c60a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/17/17ef644b8d43e32bc29577da07d4c49871b7dedfdc411bedc6f90ca66b6bae45-a
@@ -0,0 +1 @@
+v1 17ef644b8d43e32bc29577da07d4c49871b7dedfdc411bedc6f90ca66b6bae45 285a978d88032ef0dc8b9b30cae432127273a838c411ca473e46c94c8b9cb392                   21  1787953568823583188
diff --git a/.cell-installs/xdg-cache/go-build/17/17fc0ffa711d99753502323c4abe3017b7f90ba36190e6b5357b7290af7f0e1f-d b/.cell-installs/xdg-cache/go-build/17/17fc0ffa711d99753502323c4abe3017b7f90ba36190e6b5357b7290af7f0e1f-d
new file mode 100644
index 0000000..05c5043
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/17/17fc0ffa711d99753502323c4abe3017b7f90ba36190e6b5357b7290af7f0e1f-d differ
diff --git a/.cell-installs/xdg-cache/go-build/18/1809d1b301c059bb7e4c4b08bf93dbe6239b91cf43b81b18db207e0628e5d40a-a b/.cell-installs/xdg-cache/go-build/18/1809d1b301c059bb7e4c4b08bf93dbe6239b91cf43b81b18db207e0628e5d40a-a
new file mode 100644
index 0000000..b410092
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/18/1809d1b301c059bb7e4c4b08bf93dbe6239b91cf43b81b18db207e0628e5d40a-a
@@ -0,0 +1 @@
+v1 1809d1b301c059bb7e4c4b08bf93dbe6239b91cf43b81b18db207e0628e5d40a e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568861139035
diff --git a/.cell-installs/xdg-cache/go-build/18/18b833403e6da3db130420604981776d23bbf0b21084cc223baea442749af364-a b/.cell-installs/xdg-cache/go-build/18/18b833403e6da3db130420604981776d23bbf0b21084cc223baea442749af364-a
new file mode 100644
index 0000000..6e3b27c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/18/18b833403e6da3db130420604981776d23bbf0b21084cc223baea442749af364-a
@@ -0,0 +1 @@
+v1 18b833403e6da3db130420604981776d23bbf0b21084cc223baea442749af364 ecb8b81d1ac53f068c21561167a29b50f32c6de97b7c304b71f75c926fee6cb0                 7408  1787953567786654678
diff --git a/.cell-installs/xdg-cache/go-build/18/18ba4eaab7c999ade8c650439eedd35138649d166fe6a5efafb0f231f47b1b0b-d b/.cell-installs/xdg-cache/go-build/18/18ba4eaab7c999ade8c650439eedd35138649d166fe6a5efafb0f231f47b1b0b-d
new file mode 100644
index 0000000..2e3dd42
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/18/18ba4eaab7c999ade8c650439eedd35138649d166fe6a5efafb0f231f47b1b0b-d differ
diff --git a/.cell-installs/xdg-cache/go-build/19/193ae37ae79efab647839e3a670c65ba2539da0679f7e65beb2be7e92072662a-d b/.cell-installs/xdg-cache/go-build/19/193ae37ae79efab647839e3a670c65ba2539da0679f7e65beb2be7e92072662a-d
new file mode 100644
index 0000000..a3fac6a
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/19/193ae37ae79efab647839e3a670c65ba2539da0679f7e65beb2be7e92072662a-d differ
diff --git a/.cell-installs/xdg-cache/go-build/19/196ba0375cb517e166e0c9116766d75db7091952d9a9e37401527cf43c38ffc7-a b/.cell-installs/xdg-cache/go-build/19/196ba0375cb517e166e0c9116766d75db7091952d9a9e37401527cf43c38ffc7-a
new file mode 100644
index 0000000..4a004d4
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/19/196ba0375cb517e166e0c9116766d75db7091952d9a9e37401527cf43c38ffc7-a
@@ -0,0 +1 @@
+v1 196ba0375cb517e166e0c9116766d75db7091952d9a9e37401527cf43c38ffc7 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567786585086
diff --git a/.cell-installs/xdg-cache/go-build/19/196bcb8298ec68e9fd730bcd530179198ad0bb5a00c940141fb400f951b3cdc8-d b/.cell-installs/xdg-cache/go-build/19/196bcb8298ec68e9fd730bcd530179198ad0bb5a00c940141fb400f951b3cdc8-d
new file mode 100644
index 0000000..9331600
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/19/196bcb8298ec68e9fd730bcd530179198ad0bb5a00c940141fb400f951b3cdc8-d differ
diff --git a/.cell-installs/xdg-cache/go-build/19/19f716e7766c2169ad3f6112b01a0685101aee91a768ec59fb5a3289e8dd36da-a b/.cell-installs/xdg-cache/go-build/19/19f716e7766c2169ad3f6112b01a0685101aee91a768ec59fb5a3289e8dd36da-a
new file mode 100644
index 0000000..f53cfc6
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/19/19f716e7766c2169ad3f6112b01a0685101aee91a768ec59fb5a3289e8dd36da-a
@@ -0,0 +1 @@
+v1 19f716e7766c2169ad3f6112b01a0685101aee91a768ec59fb5a3289e8dd36da e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567807880046
diff --git a/.cell-installs/xdg-cache/go-build/1a/1a218a0796c6449b4bb596c74afd9f5b224d814a37f1cfcc2cf32a1d423d0319-d b/.cell-installs/xdg-cache/go-build/1a/1a218a0796c6449b4bb596c74afd9f5b224d814a37f1cfcc2cf32a1d423d0319-d
new file mode 100644
index 0000000..0b59de0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/1a/1a218a0796c6449b4bb596c74afd9f5b224d814a37f1cfcc2cf32a1d423d0319-d
@@ -0,0 +1,11 @@
+./abi.go
+./abi_amd64.go
+./compiletype.go
+./funcpc.go
+./map.go
+./stack.go
+./switch.go
+./symtab.go
+./type.go
+./abi_test.s
+./stub.s
diff --git a/.cell-installs/xdg-cache/go-build/1a/1a26b726bd95ac15b8a35b533910d0696153a775dcf31399a7e106a31a4cd70a-a b/.cell-installs/xdg-cache/go-build/1a/1a26b726bd95ac15b8a35b533910d0696153a775dcf31399a7e106a31a4cd70a-a
new file mode 100644
index 0000000..7af405b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/1a/1a26b726bd95ac15b8a35b533910d0696153a775dcf31399a7e106a31a4cd70a-a
@@ -0,0 +1 @@
+v1 1a26b726bd95ac15b8a35b533910d0696153a775dcf31399a7e106a31a4cd70a 5af8bb4e3f743174849dd3fb1709b9cd3ecb48cbbac41d4c7f1e80c62d8d7a7c               800028  1787953569991554076
diff --git a/.cell-installs/xdg-cache/go-build/1a/1a64be70ef73711c9f13a0bc9a771d46076d6073d506509764970618851d0419-a b/.cell-installs/xdg-cache/go-build/1a/1a64be70ef73711c9f13a0bc9a771d46076d6073d506509764970618851d0419-a
new file mode 100644
index 0000000..bd73dee
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/1a/1a64be70ef73711c9f13a0bc9a771d46076d6073d506509764970618851d0419-a
@@ -0,0 +1 @@
+v1 1a64be70ef73711c9f13a0bc9a771d46076d6073d506509764970618851d0419 26fd7fda47fecd05bb99b7fbc0d3b471e9fe2681533e60cccb78b17168942e7f                 3776  1787953170170676815
diff --git a/.cell-installs/xdg-cache/go-build/1a/1ae3c4b82d3d9c5a0d4cfc6ff5761a48d433d55b100c05b35e67db7341bc8ac7-d b/.cell-installs/xdg-cache/go-build/1a/1ae3c4b82d3d9c5a0d4cfc6ff5761a48d433d55b100c05b35e67db7341bc8ac7-d
new file mode 100644
index 0000000..2da410b
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/1a/1ae3c4b82d3d9c5a0d4cfc6ff5761a48d433d55b100c05b35e67db7341bc8ac7-d differ
diff --git a/.cell-installs/xdg-cache/go-build/1b/1b2df7870d96b88c8024a133487871bf8fc8dd223ec5bee00604a4cfb46f6e42-a b/.cell-installs/xdg-cache/go-build/1b/1b2df7870d96b88c8024a133487871bf8fc8dd223ec5bee00604a4cfb46f6e42-a
new file mode 100644
index 0000000..e467671
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/1b/1b2df7870d96b88c8024a133487871bf8fc8dd223ec5bee00604a4cfb46f6e42-a
@@ -0,0 +1 @@
+v1 1b2df7870d96b88c8024a133487871bf8fc8dd223ec5bee00604a4cfb46f6e42 4c9eef2e380ab5ea31cd52cbdf624a37e76c5c78f78fc4be30b1164587a33eef                  557  1787953771565171224
diff --git a/.cell-installs/xdg-cache/go-build/1b/1b948b86f6ffd7e620e9a500956155022108c921fd4d741113c19c21fdd6c98a-d b/.cell-installs/xdg-cache/go-build/1b/1b948b86f6ffd7e620e9a500956155022108c921fd4d741113c19c21fdd6c98a-d
new file mode 100644
index 0000000..542e913
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/1b/1b948b86f6ffd7e620e9a500956155022108c921fd4d741113c19c21fdd6c98a-d differ
diff --git a/.cell-installs/xdg-cache/go-build/1c/1c47c8e9f9315b11ad7f879a8d2127b31aa20f398771a16f6041d609bd14d90a-d b/.cell-installs/xdg-cache/go-build/1c/1c47c8e9f9315b11ad7f879a8d2127b31aa20f398771a16f6041d609bd14d90a-d
new file mode 100644
index 0000000..1073947
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/1c/1c47c8e9f9315b11ad7f879a8d2127b31aa20f398771a16f6041d609bd14d90a-d differ
diff --git a/.cell-installs/xdg-cache/go-build/1c/1c5f68ee50ec435d7cd738df9a1c599fe89676edc53f50e84094737af0631cf3-a b/.cell-installs/xdg-cache/go-build/1c/1c5f68ee50ec435d7cd738df9a1c599fe89676edc53f50e84094737af0631cf3-a
new file mode 100644
index 0000000..6fc279d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/1c/1c5f68ee50ec435d7cd738df9a1c599fe89676edc53f50e84094737af0631cf3-a
@@ -0,0 +1 @@
+v1 1c5f68ee50ec435d7cd738df9a1c599fe89676edc53f50e84094737af0631cf3 87ad477ba46b8e72e9ac7410d8005c730930cee575b1d172230615676bb50cff                  958  1787953170165355049
diff --git a/.cell-installs/xdg-cache/go-build/1c/1cdb08f62987cb4e32e1b27035f18b6376b2570b872edf0fa1bcdfc14f439293-d b/.cell-installs/xdg-cache/go-build/1c/1cdb08f62987cb4e32e1b27035f18b6376b2570b872edf0fa1bcdfc14f439293-d
new file mode 100644
index 0000000..f5b2be6
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/1c/1cdb08f62987cb4e32e1b27035f18b6376b2570b872edf0fa1bcdfc14f439293-d differ
diff --git a/.cell-installs/xdg-cache/go-build/1d/1d34dfde1a097165d2e5f6c14c2280687899d163868539ec093f6857366c0f20-d b/.cell-installs/xdg-cache/go-build/1d/1d34dfde1a097165d2e5f6c14c2280687899d163868539ec093f6857366c0f20-d
new file mode 100644
index 0000000..b53314a
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/1d/1d34dfde1a097165d2e5f6c14c2280687899d163868539ec093f6857366c0f20-d differ
diff --git a/.cell-installs/xdg-cache/go-build/1d/1d7de0a4a37a85ba81db03d7946fbd3cc1d567abb07bc71a5334e34747dd997e-d b/.cell-installs/xdg-cache/go-build/1d/1d7de0a4a37a85ba81db03d7946fbd3cc1d567abb07bc71a5334e34747dd997e-d
new file mode 100644
index 0000000..220cb5c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/1d/1d7de0a4a37a85ba81db03d7946fbd3cc1d567abb07bc71a5334e34747dd997e-d differ
diff --git a/.cell-installs/xdg-cache/go-build/1d/1da54450382d5c735bcba07fac4676385977fd2a4db5278cfb923728585b4a31-a b/.cell-installs/xdg-cache/go-build/1d/1da54450382d5c735bcba07fac4676385977fd2a4db5278cfb923728585b4a31-a
new file mode 100644
index 0000000..186de0a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/1d/1da54450382d5c735bcba07fac4676385977fd2a4db5278cfb923728585b4a31-a
@@ -0,0 +1 @@
+v1 1da54450382d5c735bcba07fac4676385977fd2a4db5278cfb923728585b4a31 9477228b8c3a1ced716f1005811ecd22094c74b245571eb6220dffc4e9b6ef14                  784  1787953153935743445
diff --git a/.cell-installs/xdg-cache/go-build/1d/1dac9b479556f46a99524573835fddaa69d44b703e3526e349c3ed07e9de5ad6-a b/.cell-installs/xdg-cache/go-build/1d/1dac9b479556f46a99524573835fddaa69d44b703e3526e349c3ed07e9de5ad6-a
new file mode 100644
index 0000000..4e0fe35
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/1d/1dac9b479556f46a99524573835fddaa69d44b703e3526e349c3ed07e9de5ad6-a
@@ -0,0 +1 @@
+v1 1dac9b479556f46a99524573835fddaa69d44b703e3526e349c3ed07e9de5ad6 54d3b01966fb7a0a04821fa99ad7db66a2b28976939b87a25da1b2b3ba5a50b6                  215  1787953570290638773
diff --git a/.cell-installs/xdg-cache/go-build/1e/1e1cab71c7ec26658dc2da9a9e51a78ac604a06e74e4d3f1c69d49c1a11be6d5-d b/.cell-installs/xdg-cache/go-build/1e/1e1cab71c7ec26658dc2da9a9e51a78ac604a06e74e4d3f1c69d49c1a11be6d5-d
new file mode 100644
index 0000000..2abe166
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/1e/1e1cab71c7ec26658dc2da9a9e51a78ac604a06e74e4d3f1c69d49c1a11be6d5-d differ
diff --git a/.cell-installs/xdg-cache/go-build/1e/1e30696906e91943b18ee45ff68ff32c622880ff207e55f6191c8f2f3a17b220-d b/.cell-installs/xdg-cache/go-build/1e/1e30696906e91943b18ee45ff68ff32c622880ff207e55f6191c8f2f3a17b220-d
new file mode 100644
index 0000000..6d01ab6
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/1e/1e30696906e91943b18ee45ff68ff32c622880ff207e55f6191c8f2f3a17b220-d differ
diff --git a/.cell-installs/xdg-cache/go-build/1e/1e7fedeebd58b5919f66a39e98ffc789cb9563a540b61106d74323e585f6075b-d b/.cell-installs/xdg-cache/go-build/1e/1e7fedeebd58b5919f66a39e98ffc789cb9563a540b61106d74323e585f6075b-d
new file mode 100644
index 0000000..4704389
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/1e/1e7fedeebd58b5919f66a39e98ffc789cb9563a540b61106d74323e585f6075b-d differ
diff --git a/.cell-installs/xdg-cache/go-build/1e/1ee2f8f693e2769525a9035be8008640763be555030fa2e5ba246cf41124c1e6-d b/.cell-installs/xdg-cache/go-build/1e/1ee2f8f693e2769525a9035be8008640763be555030fa2e5ba246cf41124c1e6-d
new file mode 100644
index 0000000..5a4ac08
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/1e/1ee2f8f693e2769525a9035be8008640763be555030fa2e5ba246cf41124c1e6-d differ
diff --git a/.cell-installs/xdg-cache/go-build/1f/1f1b539d1f1f379e18002936df1732227bf71add1877196f7bb11cf5575784f0-a b/.cell-installs/xdg-cache/go-build/1f/1f1b539d1f1f379e18002936df1732227bf71add1877196f7bb11cf5575784f0-a
new file mode 100644
index 0000000..dc093ca
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/1f/1f1b539d1f1f379e18002936df1732227bf71add1877196f7bb11cf5575784f0-a
@@ -0,0 +1 @@
+v1 1f1b539d1f1f379e18002936df1732227bf71add1877196f7bb11cf5575784f0 a1fa7d1d7d6df1fd0036aa80489f176556eedb29877a82fe04dc8bcaf897fcef                  798  1787953771566393257
diff --git a/.cell-installs/xdg-cache/go-build/1f/1f27ab38df98a71f7065d9843354573b3a503db3e8a12e01a62f24ba85f788bc-a b/.cell-installs/xdg-cache/go-build/1f/1f27ab38df98a71f7065d9843354573b3a503db3e8a12e01a62f24ba85f788bc-a
new file mode 100644
index 0000000..5196f5d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/1f/1f27ab38df98a71f7065d9843354573b3a503db3e8a12e01a62f24ba85f788bc-a
@@ -0,0 +1 @@
+v1 1f27ab38df98a71f7065d9843354573b3a503db3e8a12e01a62f24ba85f788bc e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570240370049
diff --git a/.cell-installs/xdg-cache/go-build/1f/1fda4cba870e7c8711d3e10c5a0ce5d10505e6268851a43499c5e179f791f9b6-a b/.cell-installs/xdg-cache/go-build/1f/1fda4cba870e7c8711d3e10c5a0ce5d10505e6268851a43499c5e179f791f9b6-a
new file mode 100644
index 0000000..03eee37
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/1f/1fda4cba870e7c8711d3e10c5a0ce5d10505e6268851a43499c5e179f791f9b6-a
@@ -0,0 +1 @@
+v1 1fda4cba870e7c8711d3e10c5a0ce5d10505e6268851a43499c5e179f791f9b6 076829fe7816678eced176c9a79582a1fb312baaa337bdf1a11e033b81e04222                 2293  1787953170151037988
diff --git a/.cell-installs/xdg-cache/go-build/1f/1ff7341e743f1e273ea80508b0cfc70cbec0bb861da6bae9628319cad0b63949-a b/.cell-installs/xdg-cache/go-build/1f/1ff7341e743f1e273ea80508b0cfc70cbec0bb861da6bae9628319cad0b63949-a
new file mode 100644
index 0000000..805b861
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/1f/1ff7341e743f1e273ea80508b0cfc70cbec0bb861da6bae9628319cad0b63949-a
@@ -0,0 +1 @@
+v1 1ff7341e743f1e273ea80508b0cfc70cbec0bb861da6bae9628319cad0b63949 3c3b03bfc830fae31e983f80a91ff876d985cd8899801293a5500652e092e7a5                   96  1787953569940310296
diff --git a/.cell-installs/xdg-cache/go-build/20/2028a4fc8620db6b8d2c0fc39c388e5680ca5bcba9a79a934333c8792cd30c89-a b/.cell-installs/xdg-cache/go-build/20/2028a4fc8620db6b8d2c0fc39c388e5680ca5bcba9a79a934333c8792cd30c89-a
new file mode 100644
index 0000000..3d18b20
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/20/2028a4fc8620db6b8d2c0fc39c388e5680ca5bcba9a79a934333c8792cd30c89-a
@@ -0,0 +1 @@
+v1 2028a4fc8620db6b8d2c0fc39c388e5680ca5bcba9a79a934333c8792cd30c89 193ae37ae79efab647839e3a670c65ba2539da0679f7e65beb2be7e92072662a                  152  1787953570316106847
diff --git a/.cell-installs/xdg-cache/go-build/20/20bd8839d0391d36e9c3d966e0ae7e24bf18cf0348b17572e3fee8f0b96a1c2c-a b/.cell-installs/xdg-cache/go-build/20/20bd8839d0391d36e9c3d966e0ae7e24bf18cf0348b17572e3fee8f0b96a1c2c-a
new file mode 100644
index 0000000..b5feb82
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/20/20bd8839d0391d36e9c3d966e0ae7e24bf18cf0348b17572e3fee8f0b96a1c2c-a
@@ -0,0 +1 @@
+v1 20bd8839d0391d36e9c3d966e0ae7e24bf18cf0348b17572e3fee8f0b96a1c2c 434e26b82091625cbcf810b85463e5ace56fbdc0810c86c69b0e6ba2a0f692c3                   46  1787953569912592130
diff --git a/.cell-installs/xdg-cache/go-build/20/20bde6268b61bdad5fe936b7fbbabe8f7c02eaa95f82716c200849cc42d59fb7-d b/.cell-installs/xdg-cache/go-build/20/20bde6268b61bdad5fe936b7fbbabe8f7c02eaa95f82716c200849cc42d59fb7-d
new file mode 100644
index 0000000..776cdcf
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/20/20bde6268b61bdad5fe936b7fbbabe8f7c02eaa95f82716c200849cc42d59fb7-d differ
diff --git a/.cell-installs/xdg-cache/go-build/20/20f4ce001d9bd834c3a0d9417eb4f3ed462b37f22a0bb15464c96e5921b9a1ca-d b/.cell-installs/xdg-cache/go-build/20/20f4ce001d9bd834c3a0d9417eb4f3ed462b37f22a0bb15464c96e5921b9a1ca-d
new file mode 100644
index 0000000..da3b0e6
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/20/20f4ce001d9bd834c3a0d9417eb4f3ed462b37f22a0bb15464c96e5921b9a1ca-d differ
diff --git a/.cell-installs/xdg-cache/go-build/21/2119038a233c74f65352b3a8b648034e2ebda67e5fc360ae0de85485cbd78353-d b/.cell-installs/xdg-cache/go-build/21/2119038a233c74f65352b3a8b648034e2ebda67e5fc360ae0de85485cbd78353-d
new file mode 100644
index 0000000..7029f01
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/21/2119038a233c74f65352b3a8b648034e2ebda67e5fc360ae0de85485cbd78353-d differ
diff --git a/.cell-installs/xdg-cache/go-build/21/212460fe841f34d0303945c678097b46f9b64a7771b9050912a6403b42f281f1-a b/.cell-installs/xdg-cache/go-build/21/212460fe841f34d0303945c678097b46f9b64a7771b9050912a6403b42f281f1-a
new file mode 100644
index 0000000..7af76c2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/21/212460fe841f34d0303945c678097b46f9b64a7771b9050912a6403b42f281f1-a
@@ -0,0 +1 @@
+v1 212460fe841f34d0303945c678097b46f9b64a7771b9050912a6403b42f281f1 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569603592943
diff --git a/.cell-installs/xdg-cache/go-build/21/2146258672473d9d8cfafbe04b5ac65c3f20adabefa507778722711591c6b6a7-a b/.cell-installs/xdg-cache/go-build/21/2146258672473d9d8cfafbe04b5ac65c3f20adabefa507778722711591c6b6a7-a
new file mode 100644
index 0000000..1e1575d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/21/2146258672473d9d8cfafbe04b5ac65c3f20adabefa507778722711591c6b6a7-a
@@ -0,0 +1 @@
+v1 2146258672473d9d8cfafbe04b5ac65c3f20adabefa507778722711591c6b6a7 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569320600723
diff --git a/.cell-installs/xdg-cache/go-build/21/217f89d6e6fb3dd3b34ccd5e29c16acfb652ac1cb00c1918d62b8fd1b2cfbffe-a b/.cell-installs/xdg-cache/go-build/21/217f89d6e6fb3dd3b34ccd5e29c16acfb652ac1cb00c1918d62b8fd1b2cfbffe-a
new file mode 100644
index 0000000..37638ca
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/21/217f89d6e6fb3dd3b34ccd5e29c16acfb652ac1cb00c1918d62b8fd1b2cfbffe-a
@@ -0,0 +1 @@
+v1 217f89d6e6fb3dd3b34ccd5e29c16acfb652ac1cb00c1918d62b8fd1b2cfbffe 6a0878351653a7d7ac30e79ee7d663e70ecd5de0c8967be2af335d9095e49df4                  511  1787953771565090546
diff --git a/.cell-installs/xdg-cache/go-build/21/21801153dfc537aeb06e64a132288ff72f7af1af566589d1224e870103453360-a b/.cell-installs/xdg-cache/go-build/21/21801153dfc537aeb06e64a132288ff72f7af1af566589d1224e870103453360-a
new file mode 100644
index 0000000..45df7e1
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/21/21801153dfc537aeb06e64a132288ff72f7af1af566589d1224e870103453360-a
@@ -0,0 +1 @@
+v1 21801153dfc537aeb06e64a132288ff72f7af1af566589d1224e870103453360 be80ce7b060af24b742092b14898158d6663136335c584992d6e0c52e895545d                  307  1787953569318629585
diff --git a/.cell-installs/xdg-cache/go-build/21/218ae71193690bdd525b087313582024526944fdfd46f5cf1d2463daa4317ca9-a b/.cell-installs/xdg-cache/go-build/21/218ae71193690bdd525b087313582024526944fdfd46f5cf1d2463daa4317ca9-a
new file mode 100644
index 0000000..95dc88f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/21/218ae71193690bdd525b087313582024526944fdfd46f5cf1d2463daa4317ca9-a
@@ -0,0 +1 @@
+v1 218ae71193690bdd525b087313582024526944fdfd46f5cf1d2463daa4317ca9 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569318187233
diff --git a/.cell-installs/xdg-cache/go-build/21/21faa15c5febcadadca5225fffd0292072de38e138bf5fe2ff635cc6450d7c4e-d b/.cell-installs/xdg-cache/go-build/21/21faa15c5febcadadca5225fffd0292072de38e138bf5fe2ff635cc6450d7c4e-d
new file mode 100644
index 0000000..e74e150
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/21/21faa15c5febcadadca5225fffd0292072de38e138bf5fe2ff635cc6450d7c4e-d
@@ -0,0 +1,3 @@
+./chacha8.go
+./chacha8_generic.go
+./chacha8_amd64.s
diff --git a/.cell-installs/xdg-cache/go-build/22/220c3eb368a151d62abea6651ea4c9d88bd44a713538b70de897ee21ff53529c-d b/.cell-installs/xdg-cache/go-build/22/220c3eb368a151d62abea6651ea4c9d88bd44a713538b70de897ee21ff53529c-d
new file mode 100644
index 0000000..bb6eaa7
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/22/220c3eb368a151d62abea6651ea4c9d88bd44a713538b70de897ee21ff53529c-d
@@ -0,0 +1,3 @@
+./interface.go
+./parser.go
+./resolver.go
diff --git a/.cell-installs/xdg-cache/go-build/22/2253e888ee6ad14dc608ad75ca2697aa57247ed7fac04061bdeb15103fe82347-a b/.cell-installs/xdg-cache/go-build/22/2253e888ee6ad14dc608ad75ca2697aa57247ed7fac04061bdeb15103fe82347-a
new file mode 100644
index 0000000..0765f7a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/22/2253e888ee6ad14dc608ad75ca2697aa57247ed7fac04061bdeb15103fe82347-a
@@ -0,0 +1 @@
+v1 2253e888ee6ad14dc608ad75ca2697aa57247ed7fac04061bdeb15103fe82347 9eb6294bc39979787b03eb7d39d5bf0cb5ae98f773ebcc790710c1d3e9773032                   25  1787954248708141625
diff --git a/.cell-installs/xdg-cache/go-build/22/229b0468e36fc3e217f478e7db00895266c046567c39176b4ebfc75ba5ce088c-d b/.cell-installs/xdg-cache/go-build/22/229b0468e36fc3e217f478e7db00895266c046567c39176b4ebfc75ba5ce088c-d
new file mode 100644
index 0000000..09e3e0a
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/22/229b0468e36fc3e217f478e7db00895266c046567c39176b4ebfc75ba5ce088c-d differ
diff --git a/.cell-installs/xdg-cache/go-build/22/22b527d5cfafa69e4c9e16e88cd869d2f0e0bce646c692ba192d1d464e172395-a b/.cell-installs/xdg-cache/go-build/22/22b527d5cfafa69e4c9e16e88cd869d2f0e0bce646c692ba192d1d464e172395-a
new file mode 100644
index 0000000..63bea2b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/22/22b527d5cfafa69e4c9e16e88cd869d2f0e0bce646c692ba192d1d464e172395-a
@@ -0,0 +1 @@
+v1 22b527d5cfafa69e4c9e16e88cd869d2f0e0bce646c692ba192d1d464e172395 86adbbb15c53775a99f62697b7e04b4648ccd5ae09c2ebf3916c7f1aa915148c                  535  1787953170139318076
diff --git a/.cell-installs/xdg-cache/go-build/22/22d1e98679504d8bc9224fb44d5009a12e093d8d5e35baa45e8f2d449126c3e7-a b/.cell-installs/xdg-cache/go-build/22/22d1e98679504d8bc9224fb44d5009a12e093d8d5e35baa45e8f2d449126c3e7-a
new file mode 100644
index 0000000..10c1058
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/22/22d1e98679504d8bc9224fb44d5009a12e093d8d5e35baa45e8f2d449126c3e7-a
@@ -0,0 +1 @@
+v1 22d1e98679504d8bc9224fb44d5009a12e093d8d5e35baa45e8f2d449126c3e7 752e4045a6dfde6aae12ce3e0faf5685918ff08e80e4707d06b5cf3fb88b4089               441310  1787953568896885835
diff --git a/.cell-installs/xdg-cache/go-build/22/22e068f63c5a6caccd0ed284491314429afbf697467b586b18f4e024fce8d313-a b/.cell-installs/xdg-cache/go-build/22/22e068f63c5a6caccd0ed284491314429afbf697467b586b18f4e024fce8d313-a
new file mode 100644
index 0000000..4eb858f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/22/22e068f63c5a6caccd0ed284491314429afbf697467b586b18f4e024fce8d313-a
@@ -0,0 +1 @@
+v1 22e068f63c5a6caccd0ed284491314429afbf697467b586b18f4e024fce8d313 686797c345e8171997651eb3fc079e5fb249dda8cca0d028da2de8062d060381                   65  1787953569878731958
diff --git a/.cell-installs/xdg-cache/go-build/22/22e5f9cc95da6a3a4c76163406e0abc474b1cf29ecfb5d64189541959ad80fdb-d b/.cell-installs/xdg-cache/go-build/22/22e5f9cc95da6a3a4c76163406e0abc474b1cf29ecfb5d64189541959ad80fdb-d
new file mode 100644
index 0000000..94dc08d
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/22/22e5f9cc95da6a3a4c76163406e0abc474b1cf29ecfb5d64189541959ad80fdb-d differ
diff --git a/.cell-installs/xdg-cache/go-build/22/22e9c935db51d7211f3ae6845f212d1a3a3ed7cc665a333e6313885584b1b5dd-d b/.cell-installs/xdg-cache/go-build/22/22e9c935db51d7211f3ae6845f212d1a3a3ed7cc665a333e6313885584b1b5dd-d
new file mode 100644
index 0000000..752a581
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/22/22e9c935db51d7211f3ae6845f212d1a3a3ed7cc665a333e6313885584b1b5dd-d
@@ -0,0 +1,4 @@
+./swapper.go
+./type.go
+./value.go
+./asm.s
diff --git a/.cell-installs/xdg-cache/go-build/23/230182bc570593810c7d1832123a9ef21b52c4e5a4eefade6bfe670ab20ffe16-d b/.cell-installs/xdg-cache/go-build/23/230182bc570593810c7d1832123a9ef21b52c4e5a4eefade6bfe670ab20ffe16-d
new file mode 100644
index 0000000..928d306
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/23/230182bc570593810c7d1832123a9ef21b52c4e5a4eefade6bfe670ab20ffe16-d differ
diff --git a/.cell-installs/xdg-cache/go-build/23/2302bafa387c1c18d2ff0e6d26c7a2f4c1885060f95719c0fe4af980e43da344-a b/.cell-installs/xdg-cache/go-build/23/2302bafa387c1c18d2ff0e6d26c7a2f4c1885060f95719c0fe4af980e43da344-a
new file mode 100644
index 0000000..7896afa
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/23/2302bafa387c1c18d2ff0e6d26c7a2f4c1885060f95719c0fe4af980e43da344-a
@@ -0,0 +1 @@
+v1 2302bafa387c1c18d2ff0e6d26c7a2f4c1885060f95719c0fe4af980e43da344 3a65a42dab5faacb13b5f0ff7546fd2cc1b8fc4958221f17180a40eb2aafce1a                   25  1787953569912904777
diff --git a/.cell-installs/xdg-cache/go-build/23/235baee0fbe6f5dce2b0a6f083378eb0d85ca5ec1187d5f5edeef6b0598635be-a b/.cell-installs/xdg-cache/go-build/23/235baee0fbe6f5dce2b0a6f083378eb0d85ca5ec1187d5f5edeef6b0598635be-a
new file mode 100644
index 0000000..b7d0677
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/23/235baee0fbe6f5dce2b0a6f083378eb0d85ca5ec1187d5f5edeef6b0598635be-a
@@ -0,0 +1 @@
+v1 235baee0fbe6f5dce2b0a6f083378eb0d85ca5ec1187d5f5edeef6b0598635be 087832261f11fa6e6fe4ec2160bd1580530b3ca62179bed9093beef47b6229f6                  147  1787953570212145579
diff --git a/.cell-installs/xdg-cache/go-build/23/235e7ef6f8ab762a7ebafc3a3e0688ddf3ddea693525f9c11cd5f972bcf6b8f8-a b/.cell-installs/xdg-cache/go-build/23/235e7ef6f8ab762a7ebafc3a3e0688ddf3ddea693525f9c11cd5f972bcf6b8f8-a
new file mode 100644
index 0000000..e95240d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/23/235e7ef6f8ab762a7ebafc3a3e0688ddf3ddea693525f9c11cd5f972bcf6b8f8-a
@@ -0,0 +1 @@
+v1 235e7ef6f8ab762a7ebafc3a3e0688ddf3ddea693525f9c11cd5f972bcf6b8f8 69a8a35487589134e88fae6e9944960fe39e95e6e490fe2cb639ab48aaa35094                   10  1787954006050308207
diff --git a/.cell-installs/xdg-cache/go-build/23/23c82ba29c157f573340674ea2e32732bd67dfb0b85a313c3b933f6b3c46b0fc-a b/.cell-installs/xdg-cache/go-build/23/23c82ba29c157f573340674ea2e32732bd67dfb0b85a313c3b933f6b3c46b0fc-a
new file mode 100644
index 0000000..9e2ef08
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/23/23c82ba29c157f573340674ea2e32732bd67dfb0b85a313c3b933f6b3c46b0fc-a
@@ -0,0 +1 @@
+v1 23c82ba29c157f573340674ea2e32732bd67dfb0b85a313c3b933f6b3c46b0fc f6498388f766cac3b2d3b1558bf2573a3d7b4c0a0f84e3a8acf629aa6c1f7606                  293  1787953771568883990
diff --git a/.cell-installs/xdg-cache/go-build/23/23eba1922a3055f8c1feff2a2d3b1dd616346789fb1052c90a79a03b07b3f4c0-d b/.cell-installs/xdg-cache/go-build/23/23eba1922a3055f8c1feff2a2d3b1dd616346789fb1052c90a79a03b07b3f4c0-d
new file mode 100644
index 0000000..8e28726
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/23/23eba1922a3055f8c1feff2a2d3b1dd616346789fb1052c90a79a03b07b3f4c0-d differ
diff --git a/.cell-installs/xdg-cache/go-build/24/243569eca8887ae182fa93c5cf3389f11ccf8a528d9e5794feff0430a3731615-a b/.cell-installs/xdg-cache/go-build/24/243569eca8887ae182fa93c5cf3389f11ccf8a528d9e5794feff0430a3731615-a
new file mode 100644
index 0000000..2975609
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/24/243569eca8887ae182fa93c5cf3389f11ccf8a528d9e5794feff0430a3731615-a
@@ -0,0 +1 @@
+v1 243569eca8887ae182fa93c5cf3389f11ccf8a528d9e5794feff0430a3731615 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569317438514
diff --git a/.cell-installs/xdg-cache/go-build/24/2437b0db881d04c69d64059e0b96eee7689336a070ba4b1c4df3a5855f71727d-a b/.cell-installs/xdg-cache/go-build/24/2437b0db881d04c69d64059e0b96eee7689336a070ba4b1c4df3a5855f71727d-a
new file mode 100644
index 0000000..0f00fa1
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/24/2437b0db881d04c69d64059e0b96eee7689336a070ba4b1c4df3a5855f71727d-a
@@ -0,0 +1 @@
+v1 2437b0db881d04c69d64059e0b96eee7689336a070ba4b1c4df3a5855f71727d 927027a932615e25ed86387f9996f7e1a1bd53c18053a5a62ad1a84bffc8fe09                 3640  1787953567787612390
diff --git a/.cell-installs/xdg-cache/go-build/24/243ed08478e9392cf0af5994a6776d279759cf8887b59d45248e03e547ebae63-d b/.cell-installs/xdg-cache/go-build/24/243ed08478e9392cf0af5994a6776d279759cf8887b59d45248e03e547ebae63-d
new file mode 100644
index 0000000..52c1cb6
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/24/243ed08478e9392cf0af5994a6776d279759cf8887b59d45248e03e547ebae63-d differ
diff --git a/.cell-installs/xdg-cache/go-build/24/244b5a8af3e4dd9ddcdae86ba5266a6207422aef96454b953ee018aaa7caa015-a b/.cell-installs/xdg-cache/go-build/24/244b5a8af3e4dd9ddcdae86ba5266a6207422aef96454b953ee018aaa7caa015-a
new file mode 100644
index 0000000..90df530
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/24/244b5a8af3e4dd9ddcdae86ba5266a6207422aef96454b953ee018aaa7caa015-a
@@ -0,0 +1 @@
+v1 244b5a8af3e4dd9ddcdae86ba5266a6207422aef96454b953ee018aaa7caa015 8501ea793151b1b9aedcd711cb27a44997ca65ae56a59afc02921571729d9dc0               280888  1787953567812541757
diff --git a/.cell-installs/xdg-cache/go-build/24/245a6e5c32f3f389f4ef7f25fb9d3ddefaff305daf83d489672cc0f62810c398-a b/.cell-installs/xdg-cache/go-build/24/245a6e5c32f3f389f4ef7f25fb9d3ddefaff305daf83d489672cc0f62810c398-a
new file mode 100644
index 0000000..66c574e
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/24/245a6e5c32f3f389f4ef7f25fb9d3ddefaff305daf83d489672cc0f62810c398-a
@@ -0,0 +1 @@
+v1 245a6e5c32f3f389f4ef7f25fb9d3ddefaff305daf83d489672cc0f62810c398 43c4af69dd2bd389aaaaeac1f3b9e24a849a2d0ab7c7f16dfbfad17ddf53d486                   44  1787953567785403589
diff --git a/.cell-installs/xdg-cache/go-build/24/24874f9d72e5877c2d301a1399ae173cd7d330b5351dae00b9e6957892dea41c-d b/.cell-installs/xdg-cache/go-build/24/24874f9d72e5877c2d301a1399ae173cd7d330b5351dae00b9e6957892dea41c-d
new file mode 100644
index 0000000..c5da235
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/24/24874f9d72e5877c2d301a1399ae173cd7d330b5351dae00b9e6957892dea41c-d differ
diff --git a/.cell-installs/xdg-cache/go-build/25/2523a88aa3aa51c9638a26fe61b0ba0e6021d71066fc40d0c77bafcb88003e6e-d b/.cell-installs/xdg-cache/go-build/25/2523a88aa3aa51c9638a26fe61b0ba0e6021d71066fc40d0c77bafcb88003e6e-d
new file mode 100644
index 0000000..e3ff64f
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/25/2523a88aa3aa51c9638a26fe61b0ba0e6021d71066fc40d0c77bafcb88003e6e-d differ
diff --git a/.cell-installs/xdg-cache/go-build/25/257e2525cbc82f04ab7948cac848d478617d1f5943ebb70e05dbdb5d7786d926-a b/.cell-installs/xdg-cache/go-build/25/257e2525cbc82f04ab7948cac848d478617d1f5943ebb70e05dbdb5d7786d926-a
new file mode 100644
index 0000000..8a10974
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/25/257e2525cbc82f04ab7948cac848d478617d1f5943ebb70e05dbdb5d7786d926-a
@@ -0,0 +1 @@
+v1 257e2525cbc82f04ab7948cac848d478617d1f5943ebb70e05dbdb5d7786d926 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569622743397
diff --git a/.cell-installs/xdg-cache/go-build/25/25cc3eb697808e962150312a12c90286e71772822eca2c5717ea75b4fa57cfbc-d b/.cell-installs/xdg-cache/go-build/25/25cc3eb697808e962150312a12c90286e71772822eca2c5717ea75b4fa57cfbc-d
new file mode 100644
index 0000000..a1cf9a4
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/25/25cc3eb697808e962150312a12c90286e71772822eca2c5717ea75b4fa57cfbc-d
@@ -0,0 +1,14 @@
+./bytealg.go
+./compare_native.go
+./count_native.go
+./equal_generic.go
+./equal_native.go
+./index_amd64.go
+./index_native.go
+./indexbyte_native.go
+./lastindexbyte_generic.go
+./compare_amd64.s
+./count_amd64.s
+./equal_amd64.s
+./index_amd64.s
+./indexbyte_amd64.s
diff --git a/.cell-installs/xdg-cache/go-build/25/25ce6d99e03bcb685e027545b42d7aea4e6a773f8d0d849d660b0acc483877ff-a b/.cell-installs/xdg-cache/go-build/25/25ce6d99e03bcb685e027545b42d7aea4e6a773f8d0d849d660b0acc483877ff-a
new file mode 100644
index 0000000..b8c66ac
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/25/25ce6d99e03bcb685e027545b42d7aea4e6a773f8d0d849d660b0acc483877ff-a
@@ -0,0 +1 @@
+v1 25ce6d99e03bcb685e027545b42d7aea4e6a773f8d0d849d660b0acc483877ff 2fcb89a651589990555b893a09438dc854c169b54457929dd039514e33531949               440842  1787953569930159193
diff --git a/.cell-installs/xdg-cache/go-build/26/264f659306e4596fb3bbd57b3fee635a562615aedbbc2da1b46a7d0f7bce8c06-a b/.cell-installs/xdg-cache/go-build/26/264f659306e4596fb3bbd57b3fee635a562615aedbbc2da1b46a7d0f7bce8c06-a
new file mode 100644
index 0000000..e13f2c6
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/26/264f659306e4596fb3bbd57b3fee635a562615aedbbc2da1b46a7d0f7bce8c06-a
@@ -0,0 +1 @@
+v1 264f659306e4596fb3bbd57b3fee635a562615aedbbc2da1b46a7d0f7bce8c06 de346962987804bd36dacb657cf4b70440956d8ae1f53f941e305a3cfc06e7ba                   46  1787953294989980502
diff --git a/.cell-installs/xdg-cache/go-build/26/2675f1f18853855f747616692d5604c13e27ca2c640009188f4976fbe88bbfe7-a b/.cell-installs/xdg-cache/go-build/26/2675f1f18853855f747616692d5604c13e27ca2c640009188f4976fbe88bbfe7-a
new file mode 100644
index 0000000..4545491
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/26/2675f1f18853855f747616692d5604c13e27ca2c640009188f4976fbe88bbfe7-a
@@ -0,0 +1 @@
+v1 2675f1f18853855f747616692d5604c13e27ca2c640009188f4976fbe88bbfe7 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570195508855
diff --git a/.cell-installs/xdg-cache/go-build/26/2678098535ffdfd0225e84332d3cd5d813ed37c01ccd86c476946d6dded63822-a b/.cell-installs/xdg-cache/go-build/26/2678098535ffdfd0225e84332d3cd5d813ed37c01ccd86c476946d6dded63822-a
new file mode 100644
index 0000000..185d385
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/26/2678098535ffdfd0225e84332d3cd5d813ed37c01ccd86c476946d6dded63822-a
@@ -0,0 +1 @@
+v1 2678098535ffdfd0225e84332d3cd5d813ed37c01ccd86c476946d6dded63822 24874f9d72e5877c2d301a1399ae173cd7d330b5351dae00b9e6957892dea41c                 2211  1787953170159242484
diff --git a/.cell-installs/xdg-cache/go-build/26/26a0f389c8232a6138b7d5b9ebc8b8d18e7ce7c2060bb291e9a3eeb6687df6ae-a b/.cell-installs/xdg-cache/go-build/26/26a0f389c8232a6138b7d5b9ebc8b8d18e7ce7c2060bb291e9a3eeb6687df6ae-a
new file mode 100644
index 0000000..25cb7d2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/26/26a0f389c8232a6138b7d5b9ebc8b8d18e7ce7c2060bb291e9a3eeb6687df6ae-a
@@ -0,0 +1 @@
+v1 26a0f389c8232a6138b7d5b9ebc8b8d18e7ce7c2060bb291e9a3eeb6687df6ae e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569325746935
diff --git a/.cell-installs/xdg-cache/go-build/26/26b09848ad953796ecfb6d71a71cde0577f832f2dbcf01e1bd68d0699851bd38-a b/.cell-installs/xdg-cache/go-build/26/26b09848ad953796ecfb6d71a71cde0577f832f2dbcf01e1bd68d0699851bd38-a
new file mode 100644
index 0000000..404b9be
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/26/26b09848ad953796ecfb6d71a71cde0577f832f2dbcf01e1bd68d0699851bd38-a
@@ -0,0 +1 @@
+v1 26b09848ad953796ecfb6d71a71cde0577f832f2dbcf01e1bd68d0699851bd38 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569233159082
diff --git a/.cell-installs/xdg-cache/go-build/26/26df7b3cd4c777f6819d66267c4886f1783ac652f6ff9f8b7a542c33d67ae990-a b/.cell-installs/xdg-cache/go-build/26/26df7b3cd4c777f6819d66267c4886f1783ac652f6ff9f8b7a542c33d67ae990-a
new file mode 100644
index 0000000..07a60e9
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/26/26df7b3cd4c777f6819d66267c4886f1783ac652f6ff9f8b7a542c33d67ae990-a
@@ -0,0 +1 @@
+v1 26df7b3cd4c777f6819d66267c4886f1783ac652f6ff9f8b7a542c33d67ae990 fbd3f0a0b1bcb06b94a210547b346183455be303d482240b6e3b775ad91141c1                   29  1787953568823378181
diff --git a/.cell-installs/xdg-cache/go-build/26/26fd7fda47fecd05bb99b7fbc0d3b471e9fe2681533e60cccb78b17168942e7f-d b/.cell-installs/xdg-cache/go-build/26/26fd7fda47fecd05bb99b7fbc0d3b471e9fe2681533e60cccb78b17168942e7f-d
new file mode 100644
index 0000000..57678c9
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/26/26fd7fda47fecd05bb99b7fbc0d3b471e9fe2681533e60cccb78b17168942e7f-d differ
diff --git a/.cell-installs/xdg-cache/go-build/27/27211dfeb84999fb1ba10cc2b314f519722bb207cd3c0a42abcef084c6d6686d-a b/.cell-installs/xdg-cache/go-build/27/27211dfeb84999fb1ba10cc2b314f519722bb207cd3c0a42abcef084c6d6686d-a
new file mode 100644
index 0000000..fff4ba9
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/27/27211dfeb84999fb1ba10cc2b314f519722bb207cd3c0a42abcef084c6d6686d-a
@@ -0,0 +1 @@
+v1 27211dfeb84999fb1ba10cc2b314f519722bb207cd3c0a42abcef084c6d6686d f5966af2f8ca82247304032a0ef73c00b22421dfe30cd7293813a0ebdd2636bd             11995616  1787953568758336380
diff --git a/.cell-installs/xdg-cache/go-build/27/27473e4552db5447bde883e109c3f73a3727f9833c1f6598ee8f26be380a96e6-a b/.cell-installs/xdg-cache/go-build/27/27473e4552db5447bde883e109c3f73a3727f9833c1f6598ee8f26be380a96e6-a
new file mode 100644
index 0000000..a838ad7
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/27/27473e4552db5447bde883e109c3f73a3727f9833c1f6598ee8f26be380a96e6-a
@@ -0,0 +1 @@
+v1 27473e4552db5447bde883e109c3f73a3727f9833c1f6598ee8f26be380a96e6 fcbd64caa252267bd01a4b9888d3f701ce98c39c4fdb2a54a99e1aa53cb88d75                35846  1787953569909665071
diff --git a/.cell-installs/xdg-cache/go-build/27/277646f5a413ac0d8cab83810eafac9d894da01ba076864f13e78ffe7d04d799-a b/.cell-installs/xdg-cache/go-build/27/277646f5a413ac0d8cab83810eafac9d894da01ba076864f13e78ffe7d04d799-a
new file mode 100644
index 0000000..782115b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/27/277646f5a413ac0d8cab83810eafac9d894da01ba076864f13e78ffe7d04d799-a
@@ -0,0 +1 @@
+v1 277646f5a413ac0d8cab83810eafac9d894da01ba076864f13e78ffe7d04d799 d9cd505cd27bfd04010bd1f0247ef1d3fadd6198270a3d128470103cd217cbde                 5446  1787953567727533644
diff --git a/.cell-installs/xdg-cache/go-build/27/278bfa22fa656c28b52b6c9be57d38afaaf3005b12c2f4124264d88b282bb2e0-a b/.cell-installs/xdg-cache/go-build/27/278bfa22fa656c28b52b6c9be57d38afaaf3005b12c2f4124264d88b282bb2e0-a
new file mode 100644
index 0000000..9a27d54
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/27/278bfa22fa656c28b52b6c9be57d38afaaf3005b12c2f4124264d88b282bb2e0-a
@@ -0,0 +1 @@
+v1 278bfa22fa656c28b52b6c9be57d38afaaf3005b12c2f4124264d88b282bb2e0 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570278610740
diff --git a/.cell-installs/xdg-cache/go-build/27/27df7d09a33d50318585c6263ade499035c74922e59a5f1f3422ffdd2c3bd3be-d b/.cell-installs/xdg-cache/go-build/27/27df7d09a33d50318585c6263ade499035c74922e59a5f1f3422ffdd2c3bd3be-d
new file mode 100644
index 0000000..5486c86
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/27/27df7d09a33d50318585c6263ade499035c74922e59a5f1f3422ffdd2c3bd3be-d differ
diff --git a/.cell-installs/xdg-cache/go-build/28/28043708092f509fa9134f4cdbca19d5cd6c87acefc6e7450a17482f328cf926-d b/.cell-installs/xdg-cache/go-build/28/28043708092f509fa9134f4cdbca19d5cd6c87acefc6e7450a17482f328cf926-d
new file mode 100644
index 0000000..3c67ff7
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/28/28043708092f509fa9134f4cdbca19d5cd6c87acefc6e7450a17482f328cf926-d
@@ -0,0 +1,9 @@
+./abi.go
+./deepequal.go
+./float32reg_generic.go
+./makefunc.go
+./swapper.go
+./type.go
+./value.go
+./visiblefields.go
+./asm_amd64.s
diff --git a/.cell-installs/xdg-cache/go-build/28/2815511898715f1b21374c7a43b352cbb8dc291b7de3a2dad436de0aba64d694-a b/.cell-installs/xdg-cache/go-build/28/2815511898715f1b21374c7a43b352cbb8dc291b7de3a2dad436de0aba64d694-a
new file mode 100644
index 0000000..d9fe936
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/28/2815511898715f1b21374c7a43b352cbb8dc291b7de3a2dad436de0aba64d694-a
@@ -0,0 +1 @@
+v1 2815511898715f1b21374c7a43b352cbb8dc291b7de3a2dad436de0aba64d694 80df895ce34aed241743e8781802b13a4f6a90b03bf5b9c1392302d7a4d7acba                  288  1787953568975567302
diff --git a/.cell-installs/xdg-cache/go-build/28/284c36926b6732100b09f789b879586d7e712edd03c04a2f9b9da60da0029be4-d b/.cell-installs/xdg-cache/go-build/28/284c36926b6732100b09f789b879586d7e712edd03c04a2f9b9da60da0029be4-d
new file mode 100644
index 0000000..9b333b8
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/28/284c36926b6732100b09f789b879586d7e712edd03c04a2f9b9da60da0029be4-d differ
diff --git a/.cell-installs/xdg-cache/go-build/28/285a978d88032ef0dc8b9b30cae432127273a838c411ca473e46c94c8b9cb392-d b/.cell-installs/xdg-cache/go-build/28/285a978d88032ef0dc8b9b30cae432127273a838c411ca473e46c94c8b9cb392-d
new file mode 100644
index 0000000..f97316a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/28/285a978d88032ef0dc8b9b30cae432127273a838c411ca473e46c94c8b9cb392-d
@@ -0,0 +1,2 @@
+./match.go
+./path.go
diff --git a/.cell-installs/xdg-cache/go-build/28/28652315f2f1a8efdcc229ab12fb9990879cad0179c64c66223cfc51010abfc2-a b/.cell-installs/xdg-cache/go-build/28/28652315f2f1a8efdcc229ab12fb9990879cad0179c64c66223cfc51010abfc2-a
new file mode 100644
index 0000000..82287f1
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/28/28652315f2f1a8efdcc229ab12fb9990879cad0179c64c66223cfc51010abfc2-a
@@ -0,0 +1 @@
+v1 28652315f2f1a8efdcc229ab12fb9990879cad0179c64c66223cfc51010abfc2 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569583901244
diff --git a/.cell-installs/xdg-cache/go-build/28/289827c8a84c01c37b743d07314f5c26249d38578de6165d94dd474ccbfe81fd-d b/.cell-installs/xdg-cache/go-build/28/289827c8a84c01c37b743d07314f5c26249d38578de6165d94dd474ccbfe81fd-d
new file mode 100644
index 0000000..47c25f0
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/28/289827c8a84c01c37b743d07314f5c26249d38578de6165d94dd474ccbfe81fd-d differ
diff --git a/.cell-installs/xdg-cache/go-build/28/28a889188865860b36c0ed3b88375c60e26f77d434380e17473e54228ac14a40-d b/.cell-installs/xdg-cache/go-build/28/28a889188865860b36c0ed3b88375c60e26f77d434380e17473e54228ac14a40-d
new file mode 100644
index 0000000..a3469c7
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/28/28a889188865860b36c0ed3b88375c60e26f77d434380e17473e54228ac14a40-d differ
diff --git a/.cell-installs/xdg-cache/go-build/28/28c97e51da30bea048e902dd6a0d6234e25468fd7de5f52ff19ba792e4bfcbac-d b/.cell-installs/xdg-cache/go-build/28/28c97e51da30bea048e902dd6a0d6234e25468fd7de5f52ff19ba792e4bfcbac-d
new file mode 100644
index 0000000..3b9c37e
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/28/28c97e51da30bea048e902dd6a0d6234e25468fd7de5f52ff19ba792e4bfcbac-d differ
diff --git a/.cell-installs/xdg-cache/go-build/28/28e2506a1632295afbc3ce95b9e239cfa75071ed51bf1780c3d1875d261d2960-a b/.cell-installs/xdg-cache/go-build/28/28e2506a1632295afbc3ce95b9e239cfa75071ed51bf1780c3d1875d261d2960-a
new file mode 100644
index 0000000..108f5cf
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/28/28e2506a1632295afbc3ce95b9e239cfa75071ed51bf1780c3d1875d261d2960-a
@@ -0,0 +1 @@
+v1 28e2506a1632295afbc3ce95b9e239cfa75071ed51bf1780c3d1875d261d2960 e9360993b5ed79d246b6e214268ef1803c5b7113b6f71b5c741cab881c66271e                  628  1787954418338252008
diff --git a/.cell-installs/xdg-cache/go-build/28/28fae9ce568588ca45b4e978e5c775e101f6526bcb2d9f34657482808d33f59e-a b/.cell-installs/xdg-cache/go-build/28/28fae9ce568588ca45b4e978e5c775e101f6526bcb2d9f34657482808d33f59e-a
new file mode 100644
index 0000000..4a45efb
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/28/28fae9ce568588ca45b4e978e5c775e101f6526bcb2d9f34657482808d33f59e-a
@@ -0,0 +1 @@
+v1 28fae9ce568588ca45b4e978e5c775e101f6526bcb2d9f34657482808d33f59e 64b9e87fca56675f53fc8c3f031cca338924a5304ca054caf7b39efe99b06b57                  970  1787953170163294602
diff --git a/.cell-installs/xdg-cache/go-build/28/28fc6b84e234dcc4cf248903b2b3644b9065ea57455e474241408d9061f7410c-a b/.cell-installs/xdg-cache/go-build/28/28fc6b84e234dcc4cf248903b2b3644b9065ea57455e474241408d9061f7410c-a
new file mode 100644
index 0000000..c1fc29b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/28/28fc6b84e234dcc4cf248903b2b3644b9065ea57455e474241408d9061f7410c-a
@@ -0,0 +1 @@
+v1 28fc6b84e234dcc4cf248903b2b3644b9065ea57455e474241408d9061f7410c e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569318164242
diff --git a/.cell-installs/xdg-cache/go-build/29/291a43954ff94e4fb31e12ad0114ebe6e52f5043ed257757f6d6a45911cfa586-d b/.cell-installs/xdg-cache/go-build/29/291a43954ff94e4fb31e12ad0114ebe6e52f5043ed257757f6d6a45911cfa586-d
new file mode 100644
index 0000000..372451c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/29/291a43954ff94e4fb31e12ad0114ebe6e52f5043ed257757f6d6a45911cfa586-d differ
diff --git a/.cell-installs/xdg-cache/go-build/29/2925eb17eb658b53fc8bef7e9f751b972d8f9143b8391e7d7ee2079e2aa5f135-d b/.cell-installs/xdg-cache/go-build/29/2925eb17eb658b53fc8bef7e9f751b972d8f9143b8391e7d7ee2079e2aa5f135-d
new file mode 100644
index 0000000..744d0b0
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/29/2925eb17eb658b53fc8bef7e9f751b972d8f9143b8391e7d7ee2079e2aa5f135-d differ
diff --git a/.cell-installs/xdg-cache/go-build/29/292d49e091039986a2af134bd04fb5a36857c914d07be395e21d6e80c341e684-a b/.cell-installs/xdg-cache/go-build/29/292d49e091039986a2af134bd04fb5a36857c914d07be395e21d6e80c341e684-a
new file mode 100644
index 0000000..5590e95
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/29/292d49e091039986a2af134bd04fb5a36857c914d07be395e21d6e80c341e684-a
@@ -0,0 +1 @@
+v1 292d49e091039986a2af134bd04fb5a36857c914d07be395e21d6e80c341e684 d43c84f157560540a3afbd6f5fd357f3a9e1226ac566ef85bcb8822ebff4c25c                  466  1787953771538112556
diff --git a/.cell-installs/xdg-cache/go-build/29/29b051b653a394836f379f6d79fca8395d130465de3003fbacf8d3cf9396f976-d b/.cell-installs/xdg-cache/go-build/29/29b051b653a394836f379f6d79fca8395d130465de3003fbacf8d3cf9396f976-d
new file mode 100644
index 0000000..8342c70
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/29/29b051b653a394836f379f6d79fca8395d130465de3003fbacf8d3cf9396f976-d
@@ -0,0 +1,3 @@
+./errors.go
+./join.go
+./wrap.go
diff --git a/.cell-installs/xdg-cache/go-build/29/29cdd5e3db1688d8d5765d4f92d85c8c3be80989ef749469b26c83354903cda7-a b/.cell-installs/xdg-cache/go-build/29/29cdd5e3db1688d8d5765d4f92d85c8c3be80989ef749469b26c83354903cda7-a
new file mode 100644
index 0000000..26c040f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/29/29cdd5e3db1688d8d5765d4f92d85c8c3be80989ef749469b26c83354903cda7-a
@@ -0,0 +1 @@
+v1 29cdd5e3db1688d8d5765d4f92d85c8c3be80989ef749469b26c83354903cda7 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570196474999
diff --git a/.cell-installs/xdg-cache/go-build/29/29d11de2a027b7eaf6f2948f6fe31b06b04a497b2a32d705689872c1a0a19432-a b/.cell-installs/xdg-cache/go-build/29/29d11de2a027b7eaf6f2948f6fe31b06b04a497b2a32d705689872c1a0a19432-a
new file mode 100644
index 0000000..e587a1e
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/29/29d11de2a027b7eaf6f2948f6fe31b06b04a497b2a32d705689872c1a0a19432-a
@@ -0,0 +1 @@
+v1 29d11de2a027b7eaf6f2948f6fe31b06b04a497b2a32d705689872c1a0a19432 c1f39a8be80ff71c36ef25b1536e5ddb2a5be820f070cea5e9b3483045eebe55                  300  1787953170154717379
diff --git a/.cell-installs/xdg-cache/go-build/2a/2a190f659df46f487caaefec8e383efdc802ecbcf8242fbc8add10c0df1be5ce-a b/.cell-installs/xdg-cache/go-build/2a/2a190f659df46f487caaefec8e383efdc802ecbcf8242fbc8add10c0df1be5ce-a
new file mode 100644
index 0000000..0be1edf
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/2a/2a190f659df46f487caaefec8e383efdc802ecbcf8242fbc8add10c0df1be5ce-a
@@ -0,0 +1 @@
+v1 2a190f659df46f487caaefec8e383efdc802ecbcf8242fbc8add10c0df1be5ce c527b8a5975959745b148a2000f3c523981a5d48ab37d39d5396b0aa7c71d1da                 1941  1787953170153069489
diff --git a/.cell-installs/xdg-cache/go-build/2a/2a8ac1860014e0368661eea9db516b73e5439f990ca4e6c7a66b90dd65418521-a b/.cell-installs/xdg-cache/go-build/2a/2a8ac1860014e0368661eea9db516b73e5439f990ca4e6c7a66b90dd65418521-a
new file mode 100644
index 0000000..e6b47f6
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/2a/2a8ac1860014e0368661eea9db516b73e5439f990ca4e6c7a66b90dd65418521-a
@@ -0,0 +1 @@
+v1 2a8ac1860014e0368661eea9db516b73e5439f990ca4e6c7a66b90dd65418521 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569608979185
diff --git a/.cell-installs/xdg-cache/go-build/2a/2ae10b24aa62c04d19c49f2b170ce6d892cbb9b51e8acd69565af5b1f3835a8c-a b/.cell-installs/xdg-cache/go-build/2a/2ae10b24aa62c04d19c49f2b170ce6d892cbb9b51e8acd69565af5b1f3835a8c-a
new file mode 100644
index 0000000..4d2b4c7
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/2a/2ae10b24aa62c04d19c49f2b170ce6d892cbb9b51e8acd69565af5b1f3835a8c-a
@@ -0,0 +1 @@
+v1 2ae10b24aa62c04d19c49f2b170ce6d892cbb9b51e8acd69565af5b1f3835a8c 4378aff0fc2711012aff605e8832606cd8ba67a5230e844873652c27d539c5f8                11620  1787953771563565283
diff --git a/.cell-installs/xdg-cache/go-build/2a/2afe7ad787290c2c39f05cf0108e4125051f96f73832d015c825eec70b05c35e-d b/.cell-installs/xdg-cache/go-build/2a/2afe7ad787290c2c39f05cf0108e4125051f96f73832d015c825eec70b05c35e-d
new file mode 100644
index 0000000..41d6f76
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/2a/2afe7ad787290c2c39f05cf0108e4125051f96f73832d015c825eec70b05c35e-d differ
diff --git a/.cell-installs/xdg-cache/go-build/2b/2b335b7be35921772aced4debc69a6a834ea5741f4b0226d70d0d047fc44e10b-a b/.cell-installs/xdg-cache/go-build/2b/2b335b7be35921772aced4debc69a6a834ea5741f4b0226d70d0d047fc44e10b-a
new file mode 100644
index 0000000..66462db
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/2b/2b335b7be35921772aced4debc69a6a834ea5741f4b0226d70d0d047fc44e10b-a
@@ -0,0 +1 @@
+v1 2b335b7be35921772aced4debc69a6a834ea5741f4b0226d70d0d047fc44e10b 0f57dbda1867ab405271f7a2b18db01bffe943f8f007122f0f9f13f5e7615bb6                   19  1787953568787825503
diff --git a/.cell-installs/xdg-cache/go-build/2b/2b3821ebbba8b53a9abc213b536e1925746064e073a6b396fa90a9cf10eba1d5-a b/.cell-installs/xdg-cache/go-build/2b/2b3821ebbba8b53a9abc213b536e1925746064e073a6b396fa90a9cf10eba1d5-a
new file mode 100644
index 0000000..26f6514
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/2b/2b3821ebbba8b53a9abc213b536e1925746064e073a6b396fa90a9cf10eba1d5-a
@@ -0,0 +1 @@
+v1 2b3821ebbba8b53a9abc213b536e1925746064e073a6b396fa90a9cf10eba1d5 22e9c935db51d7211f3ae6845f212d1a3a3ed7cc665a333e6313885584b1b5dd                   42  1787953568759260189
diff --git a/.cell-installs/xdg-cache/go-build/2b/2b6ea53237578a7af2998602d6d13eafaac3f4beedff25719f323063593ad752-a b/.cell-installs/xdg-cache/go-build/2b/2b6ea53237578a7af2998602d6d13eafaac3f4beedff25719f323063593ad752-a
new file mode 100644
index 0000000..8c310b2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/2b/2b6ea53237578a7af2998602d6d13eafaac3f4beedff25719f323063593ad752-a
@@ -0,0 +1 @@
+v1 2b6ea53237578a7af2998602d6d13eafaac3f4beedff25719f323063593ad752 193ae37ae79efab647839e3a670c65ba2539da0679f7e65beb2be7e92072662a                  152  1787953569700016479
diff --git a/.cell-installs/xdg-cache/go-build/2c/2c0bab44b84efa95c080ec8c20e83fdaec7a95659669932c54fe6f729d700e79-d b/.cell-installs/xdg-cache/go-build/2c/2c0bab44b84efa95c080ec8c20e83fdaec7a95659669932c54fe6f729d700e79-d
new file mode 100644
index 0000000..3db6159
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/2c/2c0bab44b84efa95c080ec8c20e83fdaec7a95659669932c54fe6f729d700e79-d differ
diff --git a/.cell-installs/xdg-cache/go-build/2c/2c1769ae7fbaebcd3066f14c3e883339c561eb8756e78881720074ac8dc0e286-a b/.cell-installs/xdg-cache/go-build/2c/2c1769ae7fbaebcd3066f14c3e883339c561eb8756e78881720074ac8dc0e286-a
new file mode 100644
index 0000000..1bdb1e0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/2c/2c1769ae7fbaebcd3066f14c3e883339c561eb8756e78881720074ac8dc0e286-a
@@ -0,0 +1 @@
+v1 2c1769ae7fbaebcd3066f14c3e883339c561eb8756e78881720074ac8dc0e286 8c8fa5ad132483696928c890c5eb93b690a4449f562df346eefb54a7a9bc69be                 2241  1787953771570192408
diff --git a/.cell-installs/xdg-cache/go-build/2c/2c3d9c161b933b193f2edad54bfd622720a21639238e3e65c31842dec3712f1e-a b/.cell-installs/xdg-cache/go-build/2c/2c3d9c161b933b193f2edad54bfd622720a21639238e3e65c31842dec3712f1e-a
new file mode 100644
index 0000000..e14d2ce
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/2c/2c3d9c161b933b193f2edad54bfd622720a21639238e3e65c31842dec3712f1e-a
@@ -0,0 +1 @@
+v1 2c3d9c161b933b193f2edad54bfd622720a21639238e3e65c31842dec3712f1e e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569336756349
diff --git a/.cell-installs/xdg-cache/go-build/2c/2c6eee214353b1e2363eb8b0b2fc3d18a009327898c7399f677cdf0af6df029b-d b/.cell-installs/xdg-cache/go-build/2c/2c6eee214353b1e2363eb8b0b2fc3d18a009327898c7399f677cdf0af6df029b-d
new file mode 100644
index 0000000..907627e
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/2c/2c6eee214353b1e2363eb8b0b2fc3d18a009327898c7399f677cdf0af6df029b-d differ
diff --git a/.cell-installs/xdg-cache/go-build/2c/2ccd33bb2c01fd5ea6e1786eb6030562979565f8b8a708a6f6bfd2f49236df77-a b/.cell-installs/xdg-cache/go-build/2c/2ccd33bb2c01fd5ea6e1786eb6030562979565f8b8a708a6f6bfd2f49236df77-a
new file mode 100644
index 0000000..63344ad
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/2c/2ccd33bb2c01fd5ea6e1786eb6030562979565f8b8a708a6f6bfd2f49236df77-a
@@ -0,0 +1 @@
+v1 2ccd33bb2c01fd5ea6e1786eb6030562979565f8b8a708a6f6bfd2f49236df77 9eb6294bc39979787b03eb7d39d5bf0cb5ae98f773ebcc790710c1d3e9773032                   25  1787954144023795162
diff --git a/.cell-installs/xdg-cache/go-build/2c/2ce51e95cdaf267d96cb691f0fb14affe4c79d09d3473425f0e75a017bef54ac-a b/.cell-installs/xdg-cache/go-build/2c/2ce51e95cdaf267d96cb691f0fb14affe4c79d09d3473425f0e75a017bef54ac-a
new file mode 100644
index 0000000..28938ff
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/2c/2ce51e95cdaf267d96cb691f0fb14affe4c79d09d3473425f0e75a017bef54ac-a
@@ -0,0 +1 @@
+v1 2ce51e95cdaf267d96cb691f0fb14affe4c79d09d3473425f0e75a017bef54ac e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570111129640
diff --git a/.cell-installs/xdg-cache/go-build/2c/2cfa84fae59e9789f87de1a0fa1b4b58655a08c1b36dc601618edb163d81bb43-a b/.cell-installs/xdg-cache/go-build/2c/2cfa84fae59e9789f87de1a0fa1b4b58655a08c1b36dc601618edb163d81bb43-a
new file mode 100644
index 0000000..feb22be
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/2c/2cfa84fae59e9789f87de1a0fa1b4b58655a08c1b36dc601618edb163d81bb43-a
@@ -0,0 +1 @@
+v1 2cfa84fae59e9789f87de1a0fa1b4b58655a08c1b36dc601618edb163d81bb43 3469fd497caa78a12f2467c9212f5e8df3d07aa4f3b713bbd52ee2fe0752a977                 2546  1787953567870934013
diff --git a/.cell-installs/xdg-cache/go-build/2d/2d199b3d0dcfc5c974eb390dd4cc46748aa7a279cc1ef0792a0827033f8ccefc-a b/.cell-installs/xdg-cache/go-build/2d/2d199b3d0dcfc5c974eb390dd4cc46748aa7a279cc1ef0792a0827033f8ccefc-a
new file mode 100644
index 0000000..0db81de
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/2d/2d199b3d0dcfc5c974eb390dd4cc46748aa7a279cc1ef0792a0827033f8ccefc-a
@@ -0,0 +1 @@
+v1 2d199b3d0dcfc5c974eb390dd4cc46748aa7a279cc1ef0792a0827033f8ccefc e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569318112674
diff --git a/.cell-installs/xdg-cache/go-build/2d/2dde80aed2e885be2ad9d559a9a632122930926aedc0539aa98519a66f8f6437-a b/.cell-installs/xdg-cache/go-build/2d/2dde80aed2e885be2ad9d559a9a632122930926aedc0539aa98519a66f8f6437-a
new file mode 100644
index 0000000..ed405bb
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/2d/2dde80aed2e885be2ad9d559a9a632122930926aedc0539aa98519a66f8f6437-a
@@ -0,0 +1 @@
+v1 2dde80aed2e885be2ad9d559a9a632122930926aedc0539aa98519a66f8f6437 5cb52b19fb74026997442aed74cfdbff560e13ca31c6fdb754d4e4eec040234e                18515  1787953170179751936
diff --git a/.cell-installs/xdg-cache/go-build/2d/2de356badb98e22249a6548698a2fa48aba6939d5ad67a4068b9019dfc28fb31-d b/.cell-installs/xdg-cache/go-build/2d/2de356badb98e22249a6548698a2fa48aba6939d5ad67a4068b9019dfc28fb31-d
new file mode 100644
index 0000000..a3eb9e3
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/2d/2de356badb98e22249a6548698a2fa48aba6939d5ad67a4068b9019dfc28fb31-d differ
diff --git a/.cell-installs/xdg-cache/go-build/2d/2dfaf065ced9f7b46c934514487d93332baa1ca958b2c5d8067771d83b563320-a b/.cell-installs/xdg-cache/go-build/2d/2dfaf065ced9f7b46c934514487d93332baa1ca958b2c5d8067771d83b563320-a
new file mode 100644
index 0000000..60ccd1a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/2d/2dfaf065ced9f7b46c934514487d93332baa1ca958b2c5d8067771d83b563320-a
@@ -0,0 +1 @@
+v1 2dfaf065ced9f7b46c934514487d93332baa1ca958b2c5d8067771d83b563320 4814f658ff78f1bd25654e38aa525b043246523f0e4c93bc785ca91edf232750                 1384  1787953771573458317
diff --git a/.cell-installs/xdg-cache/go-build/2e/2e452fe330d6b88e5eede315d867f3ad38c5188f98a8481b79ed5d7e8685188d-d b/.cell-installs/xdg-cache/go-build/2e/2e452fe330d6b88e5eede315d867f3ad38c5188f98a8481b79ed5d7e8685188d-d
new file mode 100644
index 0000000..7dda6c5
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/2e/2e452fe330d6b88e5eede315d867f3ad38c5188f98a8481b79ed5d7e8685188d-d differ
diff --git a/.cell-installs/xdg-cache/go-build/2e/2e519cadfc1ceebd03f810ef6b2fdd1c60e119de01ebda9ab4b548f2ff9baf29-a b/.cell-installs/xdg-cache/go-build/2e/2e519cadfc1ceebd03f810ef6b2fdd1c60e119de01ebda9ab4b548f2ff9baf29-a
new file mode 100644
index 0000000..e668368
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/2e/2e519cadfc1ceebd03f810ef6b2fdd1c60e119de01ebda9ab4b548f2ff9baf29-a
@@ -0,0 +1 @@
+v1 2e519cadfc1ceebd03f810ef6b2fdd1c60e119de01ebda9ab4b548f2ff9baf29 b48741b8a15ceff088cd60a5c707ef3e374bb7f012069cc28576ed274969a53e                   42  1787953567784777461
diff --git a/.cell-installs/xdg-cache/go-build/2e/2e784afac11430a60db4f73a57bf6a31592eb7558eb6ce8a16e4a204ad4c3fac-d b/.cell-installs/xdg-cache/go-build/2e/2e784afac11430a60db4f73a57bf6a31592eb7558eb6ce8a16e4a204ad4c3fac-d
new file mode 100644
index 0000000..8df48b1
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/2e/2e784afac11430a60db4f73a57bf6a31592eb7558eb6ce8a16e4a204ad4c3fac-d differ
diff --git a/.cell-installs/xdg-cache/go-build/2e/2ebaaf73b8275ba6d700a2c57f04dbabb4267f6f293863de0ee62a7f489a5405-a b/.cell-installs/xdg-cache/go-build/2e/2ebaaf73b8275ba6d700a2c57f04dbabb4267f6f293863de0ee62a7f489a5405-a
new file mode 100644
index 0000000..6ef48bc
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/2e/2ebaaf73b8275ba6d700a2c57f04dbabb4267f6f293863de0ee62a7f489a5405-a
@@ -0,0 +1 @@
+v1 2ebaaf73b8275ba6d700a2c57f04dbabb4267f6f293863de0ee62a7f489a5405 68354b16ff2ed0d87c1153f267cf15bc5eb2d43863676df1bc5cede120d270e9                 4942  1787953153948213499
diff --git a/.cell-installs/xdg-cache/go-build/2f/2f52bbcad7f48f13b96bbb5c5b5b3b997123b92dbcb4337b47f141bf63ce56f9-d b/.cell-installs/xdg-cache/go-build/2f/2f52bbcad7f48f13b96bbb5c5b5b3b997123b92dbcb4337b47f141bf63ce56f9-d
new file mode 100644
index 0000000..7016fa4
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/2f/2f52bbcad7f48f13b96bbb5c5b5b3b997123b92dbcb4337b47f141bf63ce56f9-d
@@ -0,0 +1,4 @@
+./backtrack.go
+./exec.go
+./onepass.go
+./regexp.go
diff --git a/.cell-installs/xdg-cache/go-build/2f/2f5ce6827da35af0f996e155f4dc54dfdfeb389171c8ece99f4aa5ee6c650c1e-d b/.cell-installs/xdg-cache/go-build/2f/2f5ce6827da35af0f996e155f4dc54dfdfeb389171c8ece99f4aa5ee6c650c1e-d
new file mode 100644
index 0000000..300eab3
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/2f/2f5ce6827da35af0f996e155f4dc54dfdfeb389171c8ece99f4aa5ee6c650c1e-d differ
diff --git a/.cell-installs/xdg-cache/go-build/2f/2f5d15f24b43049cb604cfc138d3efd8948d0b2e25baee4123b02256b19a180e-d b/.cell-installs/xdg-cache/go-build/2f/2f5d15f24b43049cb604cfc138d3efd8948d0b2e25baee4123b02256b19a180e-d
new file mode 100644
index 0000000..4760e62
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/2f/2f5d15f24b43049cb604cfc138d3efd8948d0b2e25baee4123b02256b19a180e-d differ
diff --git a/.cell-installs/xdg-cache/go-build/2f/2f5e7f599498786018f64342159d6fdde5671924d92d640ad9259829cdf7cd19-d b/.cell-installs/xdg-cache/go-build/2f/2f5e7f599498786018f64342159d6fdde5671924d92d640ad9259829cdf7cd19-d
new file mode 100644
index 0000000..0590072
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/2f/2f5e7f599498786018f64342159d6fdde5671924d92d640ad9259829cdf7cd19-d differ
diff --git a/.cell-installs/xdg-cache/go-build/2f/2fcb89a651589990555b893a09438dc854c169b54457929dd039514e33531949-d b/.cell-installs/xdg-cache/go-build/2f/2fcb89a651589990555b893a09438dc854c169b54457929dd039514e33531949-d
new file mode 100644
index 0000000..401121c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/2f/2fcb89a651589990555b893a09438dc854c169b54457929dd039514e33531949-d differ
diff --git a/.cell-installs/xdg-cache/go-build/30/30b2b77dbcf5f81df0d89c4a22ace9e3df09dd0872235211b2e719d0ea209a67-a b/.cell-installs/xdg-cache/go-build/30/30b2b77dbcf5f81df0d89c4a22ace9e3df09dd0872235211b2e719d0ea209a67-a
new file mode 100644
index 0000000..8d8f248
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/30/30b2b77dbcf5f81df0d89c4a22ace9e3df09dd0872235211b2e719d0ea209a67-a
@@ -0,0 +1 @@
+v1 30b2b77dbcf5f81df0d89c4a22ace9e3df09dd0872235211b2e719d0ea209a67 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567796763622
diff --git a/.cell-installs/xdg-cache/go-build/30/30cad5634542b05b7789ff91b5ceb76eb83639e8b0a80c8704311e8966fa0022-a b/.cell-installs/xdg-cache/go-build/30/30cad5634542b05b7789ff91b5ceb76eb83639e8b0a80c8704311e8966fa0022-a
new file mode 100644
index 0000000..953d4cd
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/30/30cad5634542b05b7789ff91b5ceb76eb83639e8b0a80c8704311e8966fa0022-a
@@ -0,0 +1 @@
+v1 30cad5634542b05b7789ff91b5ceb76eb83639e8b0a80c8704311e8966fa0022 e8a9826224983006be9b859d3b648df388afa611b65ece6a2ce39f30f569c098                  929  1787953170154553231
diff --git a/.cell-installs/xdg-cache/go-build/31/313c7beb4fffb3881f3fa64501e6f8b8f576bb038d523ffeadcbed0fc5727fa8-a b/.cell-installs/xdg-cache/go-build/31/313c7beb4fffb3881f3fa64501e6f8b8f576bb038d523ffeadcbed0fc5727fa8-a
new file mode 100644
index 0000000..6cc77a8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/31/313c7beb4fffb3881f3fa64501e6f8b8f576bb038d523ffeadcbed0fc5727fa8-a
@@ -0,0 +1 @@
+v1 313c7beb4fffb3881f3fa64501e6f8b8f576bb038d523ffeadcbed0fc5727fa8 c97111b51ccea9f80d1a06f42e0940171da4c02ff28b8b87b7e419f45f415a02              1507296  1787953569612161496
diff --git a/.cell-installs/xdg-cache/go-build/31/317534f8ea017922fa3dbda21dc4192b09ab8c5a48ad5631999702f18f5ceb54-d b/.cell-installs/xdg-cache/go-build/31/317534f8ea017922fa3dbda21dc4192b09ab8c5a48ad5631999702f18f5ceb54-d
new file mode 100644
index 0000000..afd3943
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/31/317534f8ea017922fa3dbda21dc4192b09ab8c5a48ad5631999702f18f5ceb54-d
@@ -0,0 +1,3 @@
+./goos.go
+./unix.go
+./zgoos_linux.go
diff --git a/.cell-installs/xdg-cache/go-build/31/31e2392134b5d6d81bdbaafe687f1af665fad8f93371611b0bf6b4c7dc2ad340-a b/.cell-installs/xdg-cache/go-build/31/31e2392134b5d6d81bdbaafe687f1af665fad8f93371611b0bf6b4c7dc2ad340-a
new file mode 100644
index 0000000..f733381
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/31/31e2392134b5d6d81bdbaafe687f1af665fad8f93371611b0bf6b4c7dc2ad340-a
@@ -0,0 +1 @@
+v1 31e2392134b5d6d81bdbaafe687f1af665fad8f93371611b0bf6b4c7dc2ad340 25cc3eb697808e962150312a12c90286e71772822eca2c5717ea75b4fa57cfbc                  258  1787953567809282976
diff --git a/.cell-installs/xdg-cache/go-build/32/323de96e4ea72dd671be1cdb8237a1194ea3610fc496545e67c75eea9312b989-a b/.cell-installs/xdg-cache/go-build/32/323de96e4ea72dd671be1cdb8237a1194ea3610fc496545e67c75eea9312b989-a
new file mode 100644
index 0000000..5c6378d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/32/323de96e4ea72dd671be1cdb8237a1194ea3610fc496545e67c75eea9312b989-a
@@ -0,0 +1 @@
+v1 323de96e4ea72dd671be1cdb8237a1194ea3610fc496545e67c75eea9312b989 1ee2f8f693e2769525a9035be8008640763be555030fa2e5ba246cf41124c1e6                 2360  1787953170192429444
diff --git a/.cell-installs/xdg-cache/go-build/32/3271b23531a3ea9095001435970a2cbdc65fac509b2e7df8ebcf81fded544dbc-a b/.cell-installs/xdg-cache/go-build/32/3271b23531a3ea9095001435970a2cbdc65fac509b2e7df8ebcf81fded544dbc-a
new file mode 100644
index 0000000..d646a16
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/32/3271b23531a3ea9095001435970a2cbdc65fac509b2e7df8ebcf81fded544dbc-a
@@ -0,0 +1 @@
+v1 3271b23531a3ea9095001435970a2cbdc65fac509b2e7df8ebcf81fded544dbc e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569324274407
diff --git a/.cell-installs/xdg-cache/go-build/33/339f7d0b57095368f105ac321a98665cb393e4316a9198a9c45a12aec7a040f9-a b/.cell-installs/xdg-cache/go-build/33/339f7d0b57095368f105ac321a98665cb393e4316a9198a9c45a12aec7a040f9-a
new file mode 100644
index 0000000..64542af
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/33/339f7d0b57095368f105ac321a98665cb393e4316a9198a9c45a12aec7a040f9-a
@@ -0,0 +1 @@
+v1 339f7d0b57095368f105ac321a98665cb393e4316a9198a9c45a12aec7a040f9 d93352206bc92124f0d9f2ac5dfe24548e892159a5074413a733b962c5432dc9                   12  1787953568787730108
diff --git a/.cell-installs/xdg-cache/go-build/33/33c6ce49021c4ba858fe2fa9568b18cca7072f05832990098e78760af029e4e2-a b/.cell-installs/xdg-cache/go-build/33/33c6ce49021c4ba858fe2fa9568b18cca7072f05832990098e78760af029e4e2-a
new file mode 100644
index 0000000..732a631
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/33/33c6ce49021c4ba858fe2fa9568b18cca7072f05832990098e78760af029e4e2-a
@@ -0,0 +1 @@
+v1 33c6ce49021c4ba858fe2fa9568b18cca7072f05832990098e78760af029e4e2 65682fc4a853570ad6a6d612a32aa4f25db9fb86d8e5cfc79e651d73a0445cf3                  134  1787953568759323811
diff --git a/.cell-installs/xdg-cache/go-build/33/33c905e634ccacf7e4bf9e1b24e52756568852c3e6eec3ebb68666dead77d268-a b/.cell-installs/xdg-cache/go-build/33/33c905e634ccacf7e4bf9e1b24e52756568852c3e6eec3ebb68666dead77d268-a
new file mode 100644
index 0000000..192c67e
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/33/33c905e634ccacf7e4bf9e1b24e52756568852c3e6eec3ebb68666dead77d268-a
@@ -0,0 +1 @@
+v1 33c905e634ccacf7e4bf9e1b24e52756568852c3e6eec3ebb68666dead77d268 86344d5c905c7a3cd36549cd089af7c53e1e0151d25b64f3ac88d1811f9b0c45                  578  1787953771572849734
diff --git a/.cell-installs/xdg-cache/go-build/33/33ce477939f778e80c509a8386edf4004e80d1987b2ca59dbdaf069b9fa77d1c-a b/.cell-installs/xdg-cache/go-build/33/33ce477939f778e80c509a8386edf4004e80d1987b2ca59dbdaf069b9fa77d1c-a
new file mode 100644
index 0000000..c4445f7
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/33/33ce477939f778e80c509a8386edf4004e80d1987b2ca59dbdaf069b9fa77d1c-a
@@ -0,0 +1 @@
+v1 33ce477939f778e80c509a8386edf4004e80d1987b2ca59dbdaf069b9fa77d1c e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570195095598
diff --git a/.cell-installs/xdg-cache/go-build/34/343adbb0534750a39488ac9c7386212511d8b7e0cd714b953505f6cb858d22c6-d b/.cell-installs/xdg-cache/go-build/34/343adbb0534750a39488ac9c7386212511d8b7e0cd714b953505f6cb858d22c6-d
new file mode 100644
index 0000000..213ffac
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/34/343adbb0534750a39488ac9c7386212511d8b7e0cd714b953505f6cb858d22c6-d differ
diff --git a/.cell-installs/xdg-cache/go-build/34/3469fd497caa78a12f2467c9212f5e8df3d07aa4f3b713bbd52ee2fe0752a977-d b/.cell-installs/xdg-cache/go-build/34/3469fd497caa78a12f2467c9212f5e8df3d07aa4f3b713bbd52ee2fe0752a977-d
new file mode 100644
index 0000000..acf6dc5
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/34/3469fd497caa78a12f2467c9212f5e8df3d07aa4f3b713bbd52ee2fe0752a977-d
@@ -0,0 +1,171 @@
+./alg.go
+./arena.go
+./asan0.go
+./atomic_pointer.go
+./cgo.go
+./cgo_mmap.go
+./cgo_sigaction.go
+./cgocall.go
+./cgocallback.go
+./cgocheck.go
+./chan.go
+./checkptr.go
+./compiler.go
+./complex.go
+./coro.go
+./covercounter.go
+./covermeta.go
+./cpuflags.go
+./cpuflags_amd64.go
+./cpuprof.go
+./cputicks.go
+./create_file_unix.go
+./debug.go
+./debugcall.go
+./debuglog.go
+./debuglog_off.go
+./defs_linux_amd64.go
+./env_posix.go
+./error.go
+./exithook.go
+./extern.go
+./fastlog2.go
+./fastlog2table.go
+./fds_unix.go
+./float.go
+./hash64.go
+./heapdump.go
+./histogram.go
+./iface.go
+./lfstack.go
+./lock_futex.go
+./lockrank.go
+./lockrank_off.go
+./malloc.go
+./map.go
+./map_fast32.go
+./map_fast64.go
+./map_faststr.go
+./mbarrier.go
+./mbitmap.go
+./mbitmap_allocheaders.go
+./mcache.go
+./mcentral.go
+./mcheckmark.go
+./mem.go
+./mem_linux.go
+./metrics.go
+./mfinal.go
+./mfixalloc.go
+./mgc.go
+./mgclimit.go
+./mgcmark.go
+./mgcpacer.go
+./mgcscavenge.go
+./mgcstack.go
+./mgcsweep.go
+./mgcwork.go
+./mheap.go
+./minmax.go
+./mpagealloc.go
+./mpagealloc_64bit.go
+./mpagecache.go
+./mpallocbits.go
+./mprof.go
+./mranges.go
+./msan0.go
+./msize_allocheaders.go
+./mspanset.go
+./mstats.go
+./mwbbuf.go
+./nbpipe_pipe2.go
+./netpoll.go
+./netpoll_epoll.go
+./nonwindows_stub.go
+./os_linux.go
+./os_linux_generic.go
+./os_linux_noauxv.go
+./os_linux_x86.go
+./os_nonopenbsd.go
+./os_unix.go
+./pagetrace_off.go
+./panic.go
+./pinner.go
+./plugin.go
+./preempt.go
+./preempt_nonwindows.go
+./print.go
+./proc.go
+./profbuf.go
+./proflabel.go
+./race0.go
+./rand.go
+./rdebug.go
+./retry.go
+./runtime.go
+./runtime1.go
+./runtime2.go
+./runtime_boring.go
+./rwmutex.go
+./security_linux.go
+./security_unix.go
+./select.go
+./sema.go
+./signal_amd64.go
+./signal_linux_amd64.go
+./signal_unix.go
+./sigqueue.go
+./sigqueue_note.go
+./sigtab_linux_generic.go
+./sizeclasses.go
+./slice.go
+./softfloat64.go
+./stack.go
+./stkframe.go
+./string.go
+./stubs.go
+./stubs2.go
+./stubs3.go
+./stubs_amd64.go
+./stubs_linux.go
+./symtab.go
+./symtabinl.go
+./sys_nonppc64x.go
+./sys_x86.go
+./tagptr.go
+./tagptr_64bit.go
+./test_amd64.go
+./time.go
+./time_nofake.go
+./timeasm.go
+./tls_stub.go
+./trace2.go
+./trace2buf.go
+./trace2cpu.go
+./trace2event.go
+./trace2map.go
+./trace2region.go
+./trace2runtime.go
+./trace2stack.go
+./trace2status.go
+./trace2string.go
+./trace2time.go
+./traceback.go
+./type.go
+./typekind.go
+./unsafe.go
+./utf8.go
+./vdso_elf64.go
+./vdso_linux.go
+./vdso_linux_amd64.go
+./write_err.go
+./asm.s
+./asm_amd64.s
+./duff_amd64.s
+./memclr_amd64.s
+./memmove_amd64.s
+./preempt_amd64.s
+./rt0_linux_amd64.s
+./sys_linux_amd64.s
+./test_amd64.s
+./time_linux_amd64.s
diff --git a/.cell-installs/xdg-cache/go-build/34/34cc946b40b8b3cf69eca46d5bf1a587c3f7a16022e7ace822d2b94d1bd49632-a b/.cell-installs/xdg-cache/go-build/34/34cc946b40b8b3cf69eca46d5bf1a587c3f7a16022e7ace822d2b94d1bd49632-a
new file mode 100644
index 0000000..a620536
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/34/34cc946b40b8b3cf69eca46d5bf1a587c3f7a16022e7ace822d2b94d1bd49632-a
@@ -0,0 +1 @@
+v1 34cc946b40b8b3cf69eca46d5bf1a587c3f7a16022e7ace822d2b94d1bd49632 2f5ce6827da35af0f996e155f4dc54dfdfeb389171c8ece99f4aa5ee6c650c1e              1092764  1787953570280887766
diff --git a/.cell-installs/xdg-cache/go-build/34/34d4369328ce6808ba77e0527ba900f77186b0f78d5fa73b45f4448cb2d77d96-a b/.cell-installs/xdg-cache/go-build/34/34d4369328ce6808ba77e0527ba900f77186b0f78d5fa73b45f4448cb2d77d96-a
new file mode 100644
index 0000000..3b68eae
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/34/34d4369328ce6808ba77e0527ba900f77186b0f78d5fa73b45f4448cb2d77d96-a
@@ -0,0 +1 @@
+v1 34d4369328ce6808ba77e0527ba900f77186b0f78d5fa73b45f4448cb2d77d96 901a115bbb89bb5c3042c15bebc8ae38a3ab053486a8bface4a3aff532db432a                   64  1787953567787430374
diff --git a/.cell-installs/xdg-cache/go-build/34/34ec10ebcfc18d02b5aa5dcd7722749e22b2a45efd554d33a68a14aea8006c6f-d b/.cell-installs/xdg-cache/go-build/34/34ec10ebcfc18d02b5aa5dcd7722749e22b2a45efd554d33a68a14aea8006c6f-d
new file mode 100644
index 0000000..549a3e0
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/34/34ec10ebcfc18d02b5aa5dcd7722749e22b2a45efd554d33a68a14aea8006c6f-d differ
diff --git a/.cell-installs/xdg-cache/go-build/35/355a61d674bdd089195faf60df17354ff64a2150facbf34055f7d05aa8e3c3af-a b/.cell-installs/xdg-cache/go-build/35/355a61d674bdd089195faf60df17354ff64a2150facbf34055f7d05aa8e3c3af-a
new file mode 100644
index 0000000..764e88c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/35/355a61d674bdd089195faf60df17354ff64a2150facbf34055f7d05aa8e3c3af-a
@@ -0,0 +1 @@
+v1 355a61d674bdd089195faf60df17354ff64a2150facbf34055f7d05aa8e3c3af c148cbf02843912a54af486b92131548ebad2c8a23537e864beeb1ea675f074b                 1084  1787953170165375378
diff --git a/.cell-installs/xdg-cache/go-build/36/3634d1f671e0aeb2954e88c7ab76f6799be1a38a03e95c6c2ac22d9d8326bdd5-a b/.cell-installs/xdg-cache/go-build/36/3634d1f671e0aeb2954e88c7ab76f6799be1a38a03e95c6c2ac22d9d8326bdd5-a
new file mode 100644
index 0000000..6c8e1ed
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/36/3634d1f671e0aeb2954e88c7ab76f6799be1a38a03e95c6c2ac22d9d8326bdd5-a
@@ -0,0 +1 @@
+v1 3634d1f671e0aeb2954e88c7ab76f6799be1a38a03e95c6c2ac22d9d8326bdd5 243ed08478e9392cf0af5994a6776d279759cf8887b59d45248e03e547ebae63                 4931  1787953153944749882
diff --git a/.cell-installs/xdg-cache/go-build/36/3649ca91c28b67786b59130a587e9059fd5c785dfd72228690287b55185a25df-d b/.cell-installs/xdg-cache/go-build/36/3649ca91c28b67786b59130a587e9059fd5c785dfd72228690287b55185a25df-d
new file mode 100644
index 0000000..431137f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/36/3649ca91c28b67786b59130a587e9059fd5c785dfd72228690287b55185a25df-d
@@ -0,0 +1 @@
+./typeparams.go
diff --git a/.cell-installs/xdg-cache/go-build/36/3683d5ed69bc08a3b0675dcb2aa78ca7301b2e583cd4f63daa025efa67f138f3-a b/.cell-installs/xdg-cache/go-build/36/3683d5ed69bc08a3b0675dcb2aa78ca7301b2e583cd4f63daa025efa67f138f3-a
new file mode 100644
index 0000000..dd6f7a3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/36/3683d5ed69bc08a3b0675dcb2aa78ca7301b2e583cd4f63daa025efa67f138f3-a
@@ -0,0 +1 @@
+v1 3683d5ed69bc08a3b0675dcb2aa78ca7301b2e583cd4f63daa025efa67f138f3 52b60edbd0fed54064daf07a15b87f78a645aa74efe3c949ca72799335e73c4f                10014  1787953568828960616
diff --git a/.cell-installs/xdg-cache/go-build/36/36c8d9a054c6c3885b6865bbf913a9de6e4f4ae3ebd043f781880eaa616aa598-d b/.cell-installs/xdg-cache/go-build/36/36c8d9a054c6c3885b6865bbf913a9de6e4f4ae3ebd043f781880eaa616aa598-d
new file mode 100644
index 0000000..df9e297
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/36/36c8d9a054c6c3885b6865bbf913a9de6e4f4ae3ebd043f781880eaa616aa598-d differ
diff --git a/.cell-installs/xdg-cache/go-build/36/36d5777abda623e09304529077efc3e8dbd036ca4ffe9a539550f73574106312-a b/.cell-installs/xdg-cache/go-build/36/36d5777abda623e09304529077efc3e8dbd036ca4ffe9a539550f73574106312-a
new file mode 100644
index 0000000..09643de
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/36/36d5777abda623e09304529077efc3e8dbd036ca4ffe9a539550f73574106312-a
@@ -0,0 +1 @@
+v1 36d5777abda623e09304529077efc3e8dbd036ca4ffe9a539550f73574106312 b3fe3073c134931bf550c339da960858af5e5317b3978fcbd83c781fd262ac8d                  693  1787953771570872648
diff --git a/.cell-installs/xdg-cache/go-build/37/370bb780f89a4018dd36512ab0d9013089053259987141cb0794924aef613b52-a b/.cell-installs/xdg-cache/go-build/37/370bb780f89a4018dd36512ab0d9013089053259987141cb0794924aef613b52-a
new file mode 100644
index 0000000..bef34c9
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/37/370bb780f89a4018dd36512ab0d9013089053259987141cb0794924aef613b52-a
@@ -0,0 +1 @@
+v1 370bb780f89a4018dd36512ab0d9013089053259987141cb0794924aef613b52 e86af54ff100e0a34a7be3d786ca322d4fa0db1a8c0dca6c5b08a3cc2b0dc19b                  137  1787953154047021080
diff --git a/.cell-installs/xdg-cache/go-build/37/373b941e4336a16485c9f03c7ad55914b794cd15c18d4959e6e93447b1f79bc3-d b/.cell-installs/xdg-cache/go-build/37/373b941e4336a16485c9f03c7ad55914b794cd15c18d4959e6e93447b1f79bc3-d
new file mode 100644
index 0000000..d933989
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/37/373b941e4336a16485c9f03c7ad55914b794cd15c18d4959e6e93447b1f79bc3-d differ
diff --git a/.cell-installs/xdg-cache/go-build/37/37c5e30361af8a3e72b9f97d97d99c69afaf92498aa14f13c74884ab8e4b5541-a b/.cell-installs/xdg-cache/go-build/37/37c5e30361af8a3e72b9f97d97d99c69afaf92498aa14f13c74884ab8e4b5541-a
new file mode 100644
index 0000000..dd2389e
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/37/37c5e30361af8a3e72b9f97d97d99c69afaf92498aa14f13c74884ab8e4b5541-a
@@ -0,0 +1 @@
+v1 37c5e30361af8a3e72b9f97d97d99c69afaf92498aa14f13c74884ab8e4b5541 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569915673029
diff --git a/.cell-installs/xdg-cache/go-build/37/37d4c7c3dfbee05fc71faad3db98f5a015a8516b3cd042850c0d9e8bfdda3d33-d b/.cell-installs/xdg-cache/go-build/37/37d4c7c3dfbee05fc71faad3db98f5a015a8516b3cd042850c0d9e8bfdda3d33-d
new file mode 100644
index 0000000..aa1a051
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/37/37d4c7c3dfbee05fc71faad3db98f5a015a8516b3cd042850c0d9e8bfdda3d33-d differ
diff --git a/.cell-installs/xdg-cache/go-build/37/37d8ec940a8815923611588a58ff250f42d2af15902247320c8fcb4d40a95bb2-a b/.cell-installs/xdg-cache/go-build/37/37d8ec940a8815923611588a58ff250f42d2af15902247320c8fcb4d40a95bb2-a
new file mode 100644
index 0000000..0d223e5
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/37/37d8ec940a8815923611588a58ff250f42d2af15902247320c8fcb4d40a95bb2-a
@@ -0,0 +1 @@
+v1 37d8ec940a8815923611588a58ff250f42d2af15902247320c8fcb4d40a95bb2 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567786453869
diff --git a/.cell-installs/xdg-cache/go-build/37/37d9aa811a8a5d09d4399abc94cfdc2c7e7f085f96fdbaa66c59f871bae454ed-d b/.cell-installs/xdg-cache/go-build/37/37d9aa811a8a5d09d4399abc94cfdc2c7e7f085f96fdbaa66c59f871bae454ed-d
new file mode 100644
index 0000000..773b8a7
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/37/37d9aa811a8a5d09d4399abc94cfdc2c7e7f085f96fdbaa66c59f871bae454ed-d differ
diff --git a/.cell-installs/xdg-cache/go-build/38/385defb2c1004e3d6ca9b8d6589d2fbc218b94a5bea622df8b70a11128427643-a b/.cell-installs/xdg-cache/go-build/38/385defb2c1004e3d6ca9b8d6589d2fbc218b94a5bea622df8b70a11128427643-a
new file mode 100644
index 0000000..a4933c5
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/38/385defb2c1004e3d6ca9b8d6589d2fbc218b94a5bea622df8b70a11128427643-a
@@ -0,0 +1 @@
+v1 385defb2c1004e3d6ca9b8d6589d2fbc218b94a5bea622df8b70a11128427643 1722e39b2eec812fae3b211d6e60f4a433f0d07a5be681d4de36532e00aac03c                   21  1787953567749663477
diff --git a/.cell-installs/xdg-cache/go-build/38/387fa67aea3fb81a309b629d267bc53ec59d69630f9b53debf367ac65f9543d5-a b/.cell-installs/xdg-cache/go-build/38/387fa67aea3fb81a309b629d267bc53ec59d69630f9b53debf367ac65f9543d5-a
new file mode 100644
index 0000000..174aacf
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/38/387fa67aea3fb81a309b629d267bc53ec59d69630f9b53debf367ac65f9543d5-a
@@ -0,0 +1 @@
+v1 387fa67aea3fb81a309b629d267bc53ec59d69630f9b53debf367ac65f9543d5 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569910102332
diff --git a/.cell-installs/xdg-cache/go-build/39/39016132c0df8b02c01230097e32b5ef7c77b0fa182a5e3752d0953eaa16a835-a b/.cell-installs/xdg-cache/go-build/39/39016132c0df8b02c01230097e32b5ef7c77b0fa182a5e3752d0953eaa16a835-a
new file mode 100644
index 0000000..fc52e2b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/39/39016132c0df8b02c01230097e32b5ef7c77b0fa182a5e3752d0953eaa16a835-a
@@ -0,0 +1 @@
+v1 39016132c0df8b02c01230097e32b5ef7c77b0fa182a5e3752d0953eaa16a835 a96c3f482bddb82ba088d27c3b2526ead9a3d2a41997834be6096bf14eebcc29                 1989  1787953170154777573
diff --git a/.cell-installs/xdg-cache/go-build/39/39201e26192f669f2c3aea560a5136daedf564b8c39a40f0e78413698fca4529-d b/.cell-installs/xdg-cache/go-build/39/39201e26192f669f2c3aea560a5136daedf564b8c39a40f0e78413698fca4529-d
new file mode 100644
index 0000000..ce53742
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/39/39201e26192f669f2c3aea560a5136daedf564b8c39a40f0e78413698fca4529-d differ
diff --git a/.cell-installs/xdg-cache/go-build/39/3945647523564f2159aec59fb5784210305ddf307b7ae65eb33a3f671636aa69-a b/.cell-installs/xdg-cache/go-build/39/3945647523564f2159aec59fb5784210305ddf307b7ae65eb33a3f671636aa69-a
new file mode 100644
index 0000000..0903bcb
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/39/3945647523564f2159aec59fb5784210305ddf307b7ae65eb33a3f671636aa69-a
@@ -0,0 +1 @@
+v1 3945647523564f2159aec59fb5784210305ddf307b7ae65eb33a3f671636aa69 5bdc54d77bedcfdb99dbea0ea5f7f03c16ef490b6018bb76e9f275d132092c56                  821  1787953170145556040
diff --git a/.cell-installs/xdg-cache/go-build/39/39bd39fba732f09f0d9e114f063e979e0877d835f42dc2b074eaffb62e90670c-d b/.cell-installs/xdg-cache/go-build/39/39bd39fba732f09f0d9e114f063e979e0877d835f42dc2b074eaffb62e90670c-d
new file mode 100644
index 0000000..b5d477c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/39/39bd39fba732f09f0d9e114f063e979e0877d835f42dc2b074eaffb62e90670c-d differ
diff --git a/.cell-installs/xdg-cache/go-build/39/39fe3d5b12860bd4927fce25f8b96076dfb489dbda5449d5e2ad797b699f4c39-a b/.cell-installs/xdg-cache/go-build/39/39fe3d5b12860bd4927fce25f8b96076dfb489dbda5449d5e2ad797b699f4c39-a
new file mode 100644
index 0000000..9beba11
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/39/39fe3d5b12860bd4927fce25f8b96076dfb489dbda5449d5e2ad797b699f4c39-a
@@ -0,0 +1 @@
+v1 39fe3d5b12860bd4927fce25f8b96076dfb489dbda5449d5e2ad797b699f4c39 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567794650194
diff --git a/.cell-installs/xdg-cache/go-build/3a/3a04d728de8df17525764461746ef224a07da074ed44c0039d2509975c5b29ca-d b/.cell-installs/xdg-cache/go-build/3a/3a04d728de8df17525764461746ef224a07da074ed44c0039d2509975c5b29ca-d
new file mode 100644
index 0000000..0ebf109
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/3a/3a04d728de8df17525764461746ef224a07da074ed44c0039d2509975c5b29ca-d differ
diff --git a/.cell-installs/xdg-cache/go-build/3a/3a2247463477d7161e05902eae24cac571de58aeebaebc346c2861e077ee233c-d b/.cell-installs/xdg-cache/go-build/3a/3a2247463477d7161e05902eae24cac571de58aeebaebc346c2861e077ee233c-d
new file mode 100644
index 0000000..7078452
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3a/3a2247463477d7161e05902eae24cac571de58aeebaebc346c2861e077ee233c-d
@@ -0,0 +1 @@
+./cmp.go
diff --git a/.cell-installs/xdg-cache/go-build/3a/3a3b341cc01f7a06ddab367e97ea85fad0c6cd781070cb7755fc41e90f67c436-a b/.cell-installs/xdg-cache/go-build/3a/3a3b341cc01f7a06ddab367e97ea85fad0c6cd781070cb7755fc41e90f67c436-a
new file mode 100644
index 0000000..a2031af
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3a/3a3b341cc01f7a06ddab367e97ea85fad0c6cd781070cb7755fc41e90f67c436-a
@@ -0,0 +1 @@
+v1 3a3b341cc01f7a06ddab367e97ea85fad0c6cd781070cb7755fc41e90f67c436 670c81db1b68ac74da78adbe0747ec16c63ed7057b46fe396aa7096609d7e5c6                  262  1787953771564556041
diff --git a/.cell-installs/xdg-cache/go-build/3a/3a65a42dab5faacb13b5f0ff7546fd2cc1b8fc4958221f17180a40eb2aafce1a-d b/.cell-installs/xdg-cache/go-build/3a/3a65a42dab5faacb13b5f0ff7546fd2cc1b8fc4958221f17180a40eb2aafce1a-d
new file mode 100644
index 0000000..985bb44
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3a/3a65a42dab5faacb13b5f0ff7546fd2cc1b8fc4958221f17180a40eb2aafce1a-d
@@ -0,0 +1,2 @@
+./errors.go
+./scanner.go
diff --git a/.cell-installs/xdg-cache/go-build/3a/3a8b030bc929718edd1cb40f68ea2afb4ce3e2cfd889e9d9f987b8266bfc09c0-a b/.cell-installs/xdg-cache/go-build/3a/3a8b030bc929718edd1cb40f68ea2afb4ce3e2cfd889e9d9f987b8266bfc09c0-a
new file mode 100644
index 0000000..0b74894
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3a/3a8b030bc929718edd1cb40f68ea2afb4ce3e2cfd889e9d9f987b8266bfc09c0-a
@@ -0,0 +1 @@
+v1 3a8b030bc929718edd1cb40f68ea2afb4ce3e2cfd889e9d9f987b8266bfc09c0 987426449d1a375ac18d83fe739c2f6325ae4917a74852a84e75ee25a38eacfc                 1519  1787953153943054500
diff --git a/.cell-installs/xdg-cache/go-build/3a/3abd5dbda947eee81faa79570935e432e4115b53423f1fb4c3f75a8fbdc2f10a-a b/.cell-installs/xdg-cache/go-build/3a/3abd5dbda947eee81faa79570935e432e4115b53423f1fb4c3f75a8fbdc2f10a-a
new file mode 100644
index 0000000..77a75a5
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3a/3abd5dbda947eee81faa79570935e432e4115b53423f1fb4c3f75a8fbdc2f10a-a
@@ -0,0 +1 @@
+v1 3abd5dbda947eee81faa79570935e432e4115b53423f1fb4c3f75a8fbdc2f10a de8028b6f1a7f4238222d95ecb8587390d751ba98d2b512a9a4437ec3c73d506               100206  1787953567808186617
diff --git a/.cell-installs/xdg-cache/go-build/3b/3b0d5024b59175a57b2d6cd3cfde58e2bd3504d79addab57b7230d5363e628c6-d b/.cell-installs/xdg-cache/go-build/3b/3b0d5024b59175a57b2d6cd3cfde58e2bd3504d79addab57b7230d5363e628c6-d
new file mode 100644
index 0000000..d3355f3
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/3b/3b0d5024b59175a57b2d6cd3cfde58e2bd3504d79addab57b7230d5363e628c6-d differ
diff --git a/.cell-installs/xdg-cache/go-build/3b/3b0f51d1fc94420f61b79e4fdef21501fa8c6c018b446b6c780de99c4fda1296-d b/.cell-installs/xdg-cache/go-build/3b/3b0f51d1fc94420f61b79e4fdef21501fa8c6c018b446b6c780de99c4fda1296-d
new file mode 100644
index 0000000..2d49708
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/3b/3b0f51d1fc94420f61b79e4fdef21501fa8c6c018b446b6c780de99c4fda1296-d differ
diff --git a/.cell-installs/xdg-cache/go-build/3b/3b12b583e728ed474e41737a537cc0e755352ed642ab6dfc82030c9662ffedb0-a b/.cell-installs/xdg-cache/go-build/3b/3b12b583e728ed474e41737a537cc0e755352ed642ab6dfc82030c9662ffedb0-a
new file mode 100644
index 0000000..936461b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3b/3b12b583e728ed474e41737a537cc0e755352ed642ab6dfc82030c9662ffedb0-a
@@ -0,0 +1 @@
+v1 3b12b583e728ed474e41737a537cc0e755352ed642ab6dfc82030c9662ffedb0 7c5093ddf9c5bd71ee82cbd24a6ae7d3a12ce14a25ce055383eeca80186acc1d               127250  1787953569947342323
diff --git a/.cell-installs/xdg-cache/go-build/3b/3bfdde117bc14d60ad31a0c40bf88d9f597ee4f635b552089f69d10e3ff80099-d b/.cell-installs/xdg-cache/go-build/3b/3bfdde117bc14d60ad31a0c40bf88d9f597ee4f635b552089f69d10e3ff80099-d
new file mode 100644
index 0000000..251890c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/3b/3bfdde117bc14d60ad31a0c40bf88d9f597ee4f635b552089f69d10e3ff80099-d differ
diff --git a/.cell-installs/xdg-cache/go-build/3c/3c018ffc4e03d1080358c6cda13fc40856f4935dc7563dd794ce165cf1bcea5d-a b/.cell-installs/xdg-cache/go-build/3c/3c018ffc4e03d1080358c6cda13fc40856f4935dc7563dd794ce165cf1bcea5d-a
new file mode 100644
index 0000000..86adada
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3c/3c018ffc4e03d1080358c6cda13fc40856f4935dc7563dd794ce165cf1bcea5d-a
@@ -0,0 +1 @@
+v1 3c018ffc4e03d1080358c6cda13fc40856f4935dc7563dd794ce165cf1bcea5d 3b0f51d1fc94420f61b79e4fdef21501fa8c6c018b446b6c780de99c4fda1296                  403  1787953154047418859
diff --git a/.cell-installs/xdg-cache/go-build/3c/3c189a4349d1ade7bd53b9153bc0f9ca1d0b336803545275deddcd24af535f0f-a b/.cell-installs/xdg-cache/go-build/3c/3c189a4349d1ade7bd53b9153bc0f9ca1d0b336803545275deddcd24af535f0f-a
new file mode 100644
index 0000000..f83d363
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3c/3c189a4349d1ade7bd53b9153bc0f9ca1d0b336803545275deddcd24af535f0f-a
@@ -0,0 +1 @@
+v1 3c189a4349d1ade7bd53b9153bc0f9ca1d0b336803545275deddcd24af535f0f e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569700121609
diff --git a/.cell-installs/xdg-cache/go-build/3c/3c3b03bfc830fae31e983f80a91ff876d985cd8899801293a5500652e092e7a5-d b/.cell-installs/xdg-cache/go-build/3c/3c3b03bfc830fae31e983f80a91ff876d985cd8899801293a5500652e092e7a5-d
new file mode 100644
index 0000000..b56a678
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3c/3c3b03bfc830fae31e983f80a91ff876d985cd8899801293a5500652e092e7a5-d
@@ -0,0 +1,5 @@
+./sha256.go
+./sha256block.go
+./sha256block_amd64.go
+./sha256block_decl.go
+./sha256block_amd64.s
diff --git a/.cell-installs/xdg-cache/go-build/3c/3c5f05d096392780385c30770996d9df89396a3947c7599d6b45c621798e3c70-a b/.cell-installs/xdg-cache/go-build/3c/3c5f05d096392780385c30770996d9df89396a3947c7599d6b45c621798e3c70-a
new file mode 100644
index 0000000..e25bfac
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3c/3c5f05d096392780385c30770996d9df89396a3947c7599d6b45c621798e3c70-a
@@ -0,0 +1 @@
+v1 3c5f05d096392780385c30770996d9df89396a3947c7599d6b45c621798e3c70 1ae3c4b82d3d9c5a0d4cfc6ff5761a48d433d55b100c05b35e67db7341bc8ac7               351446  1787953569338203866
diff --git a/.cell-installs/xdg-cache/go-build/3c/3ca9f3d86328521b7ebdb67d2b142e225314e20995659acbecd86973d5c5a06e-d b/.cell-installs/xdg-cache/go-build/3c/3ca9f3d86328521b7ebdb67d2b142e225314e20995659acbecd86973d5c5a06e-d
new file mode 100644
index 0000000..38389a9
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/3c/3ca9f3d86328521b7ebdb67d2b142e225314e20995659acbecd86973d5c5a06e-d differ
diff --git a/.cell-installs/xdg-cache/go-build/3c/3cdb80c8c17e7042fe310e8ea0e480be891dc7d07be9f66397f1c2d279909291-a b/.cell-installs/xdg-cache/go-build/3c/3cdb80c8c17e7042fe310e8ea0e480be891dc7d07be9f66397f1c2d279909291-a
new file mode 100644
index 0000000..976f946
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3c/3cdb80c8c17e7042fe310e8ea0e480be891dc7d07be9f66397f1c2d279909291-a
@@ -0,0 +1 @@
+v1 3cdb80c8c17e7042fe310e8ea0e480be891dc7d07be9f66397f1c2d279909291 34ec10ebcfc18d02b5aa5dcd7722749e22b2a45efd554d33a68a14aea8006c6f                  558  1787953771567745066
diff --git a/.cell-installs/xdg-cache/go-build/3d/3d28b27680ce8e28a02a29123ba5aa2aa44c9460f22dc6e4429ae84fd69e6a13-a b/.cell-installs/xdg-cache/go-build/3d/3d28b27680ce8e28a02a29123ba5aa2aa44c9460f22dc6e4429ae84fd69e6a13-a
new file mode 100644
index 0000000..cd146f5
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3d/3d28b27680ce8e28a02a29123ba5aa2aa44c9460f22dc6e4429ae84fd69e6a13-a
@@ -0,0 +1 @@
+v1 3d28b27680ce8e28a02a29123ba5aa2aa44c9460f22dc6e4429ae84fd69e6a13 2de356badb98e22249a6548698a2fa48aba6939d5ad67a4068b9019dfc28fb31                 1703  1787953771566033504
diff --git a/.cell-installs/xdg-cache/go-build/3d/3d46986aa28d466dbccdef4404b3bed438392a8f3676c4e0220d6a7e1bebe40e-a b/.cell-installs/xdg-cache/go-build/3d/3d46986aa28d466dbccdef4404b3bed438392a8f3676c4e0220d6a7e1bebe40e-a
new file mode 100644
index 0000000..a57992f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3d/3d46986aa28d466dbccdef4404b3bed438392a8f3676c4e0220d6a7e1bebe40e-a
@@ -0,0 +1 @@
+v1 3d46986aa28d466dbccdef4404b3bed438392a8f3676c4e0220d6a7e1bebe40e efa1427b4a2b626f263187d1f8551aaf9fa0d92f6abfcdade25c3f0eb7780a00               319402  1787953568856769905
diff --git a/.cell-installs/xdg-cache/go-build/3d/3dae157c5c9a9607e16281a1618f62e921d5b862049fdf6ca95ecc8b6b151d2f-a b/.cell-installs/xdg-cache/go-build/3d/3dae157c5c9a9607e16281a1618f62e921d5b862049fdf6ca95ecc8b6b151d2f-a
new file mode 100644
index 0000000..d2dd1ca
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3d/3dae157c5c9a9607e16281a1618f62e921d5b862049fdf6ca95ecc8b6b151d2f-a
@@ -0,0 +1 @@
+v1 3dae157c5c9a9607e16281a1618f62e921d5b862049fdf6ca95ecc8b6b151d2f 8e9e7b7cc6a2194d4e2d1d83b289bf5347486db429dfc6fb5dee25de64bc9256                 5377  1787953153953521788
diff --git a/.cell-installs/xdg-cache/go-build/3d/3ddb873743914ae4dda4093b4d6851b93b57184fa8366b554692f21bbf0e0f29-d b/.cell-installs/xdg-cache/go-build/3d/3ddb873743914ae4dda4093b4d6851b93b57184fa8366b554692f21bbf0e0f29-d
new file mode 100644
index 0000000..cd25d96
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/3d/3ddb873743914ae4dda4093b4d6851b93b57184fa8366b554692f21bbf0e0f29-d differ
diff --git a/.cell-installs/xdg-cache/go-build/3e/3e488f4e66755c65ce78e8d5bca41d899e9bd0a0d16a51f514a1ec2fbb63bb2b-d b/.cell-installs/xdg-cache/go-build/3e/3e488f4e66755c65ce78e8d5bca41d899e9bd0a0d16a51f514a1ec2fbb63bb2b-d
new file mode 100644
index 0000000..6a0e7d7
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/3e/3e488f4e66755c65ce78e8d5bca41d899e9bd0a0d16a51f514a1ec2fbb63bb2b-d differ
diff --git a/.cell-installs/xdg-cache/go-build/3e/3ec496f7e72d60d66b2915f3cf8975bb94b79c4d57e08c3f65fedf46eb5d0339-d b/.cell-installs/xdg-cache/go-build/3e/3ec496f7e72d60d66b2915f3cf8975bb94b79c4d57e08c3f65fedf46eb5d0339-d
new file mode 100644
index 0000000..78cadce
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/3e/3ec496f7e72d60d66b2915f3cf8975bb94b79c4d57e08c3f65fedf46eb5d0339-d differ
diff --git a/.cell-installs/xdg-cache/go-build/3e/3effb769234dacb397c3e5f26bad37b8d9161cb124627446e51d1c3ab433e985-d b/.cell-installs/xdg-cache/go-build/3e/3effb769234dacb397c3e5f26bad37b8d9161cb124627446e51d1c3ab433e985-d
new file mode 100644
index 0000000..fe06591
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/3e/3effb769234dacb397c3e5f26bad37b8d9161cb124627446e51d1c3ab433e985-d differ
diff --git a/.cell-installs/xdg-cache/go-build/3f/3f0e747d8c7c26f9061297bcb9ef3ed3bb8d721f9b9d2eac32b339912c2e716e-a b/.cell-installs/xdg-cache/go-build/3f/3f0e747d8c7c26f9061297bcb9ef3ed3bb8d721f9b9d2eac32b339912c2e716e-a
new file mode 100644
index 0000000..695e464
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3f/3f0e747d8c7c26f9061297bcb9ef3ed3bb8d721f9b9d2eac32b339912c2e716e-a
@@ -0,0 +1 @@
+v1 3f0e747d8c7c26f9061297bcb9ef3ed3bb8d721f9b9d2eac32b339912c2e716e e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568807131316
diff --git a/.cell-installs/xdg-cache/go-build/3f/3f40f5817f9456f374f65507bc8ca167f069a178bd5d671b558a98281cae8b32-a b/.cell-installs/xdg-cache/go-build/3f/3f40f5817f9456f374f65507bc8ca167f069a178bd5d671b558a98281cae8b32-a
new file mode 100644
index 0000000..f331a62
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3f/3f40f5817f9456f374f65507bc8ca167f069a178bd5d671b558a98281cae8b32-a
@@ -0,0 +1 @@
+v1 3f40f5817f9456f374f65507bc8ca167f069a178bd5d671b558a98281cae8b32 46a65602b2f1a724b1d27169766dae76b2a217f50c9f3ea0db64c0dfc6fd51be                  956  1787953170154575721
diff --git a/.cell-installs/xdg-cache/go-build/3f/3f839e0cb483e8a6f3477e94803e7e9c968d1e0ef9493f7727f759d7a2b43c4e-a b/.cell-installs/xdg-cache/go-build/3f/3f839e0cb483e8a6f3477e94803e7e9c968d1e0ef9493f7727f759d7a2b43c4e-a
new file mode 100644
index 0000000..cf42a6c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3f/3f839e0cb483e8a6f3477e94803e7e9c968d1e0ef9493f7727f759d7a2b43c4e-a
@@ -0,0 +1 @@
+v1 3f839e0cb483e8a6f3477e94803e7e9c968d1e0ef9493f7727f759d7a2b43c4e f34b86d507ef6a53c07741acc43feea0f473e34317b17e5901a8ea0ef54bc589                 8661  1787953170173691806
diff --git a/.cell-installs/xdg-cache/go-build/3f/3fdb13df8c19982c363e0858761cd2604ab9210c03d3ae820879c78a9726d25f-a b/.cell-installs/xdg-cache/go-build/3f/3fdb13df8c19982c363e0858761cd2604ab9210c03d3ae820879c78a9726d25f-a
new file mode 100644
index 0000000..bfba491
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/3f/3fdb13df8c19982c363e0858761cd2604ab9210c03d3ae820879c78a9726d25f-a
@@ -0,0 +1 @@
+v1 3fdb13df8c19982c363e0858761cd2604ab9210c03d3ae820879c78a9726d25f e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569872294814
diff --git a/.cell-installs/xdg-cache/go-build/40/4083f51d30100984bc476511835728906849353484dbfc991f25cf8ad53e75e4-d b/.cell-installs/xdg-cache/go-build/40/4083f51d30100984bc476511835728906849353484dbfc991f25cf8ad53e75e4-d
new file mode 100644
index 0000000..634f67f
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/40/4083f51d30100984bc476511835728906849353484dbfc991f25cf8ad53e75e4-d differ
diff --git a/.cell-installs/xdg-cache/go-build/40/4095921765a2d49cddf8171397d59e68e1ead30307e862684e6f948ec3c8dd87-a b/.cell-installs/xdg-cache/go-build/40/4095921765a2d49cddf8171397d59e68e1ead30307e862684e6f948ec3c8dd87-a
new file mode 100644
index 0000000..fc6686b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/40/4095921765a2d49cddf8171397d59e68e1ead30307e862684e6f948ec3c8dd87-a
@@ -0,0 +1 @@
+v1 4095921765a2d49cddf8171397d59e68e1ead30307e862684e6f948ec3c8dd87 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569128045378
diff --git a/.cell-installs/xdg-cache/go-build/40/40a4dbdea6ad55f7c0a1d3dc2e23ba9bb39c0f74be66c2ca48121cd0146c8bb5-d b/.cell-installs/xdg-cache/go-build/40/40a4dbdea6ad55f7c0a1d3dc2e23ba9bb39c0f74be66c2ca48121cd0146c8bb5-d
new file mode 100644
index 0000000..abddbaf
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/40/40a4dbdea6ad55f7c0a1d3dc2e23ba9bb39c0f74be66c2ca48121cd0146c8bb5-d
@@ -0,0 +1,36 @@
+./dir.go
+./dir_unix.go
+./dirent_linux.go
+./endian_little.go
+./env.go
+./error.go
+./error_errno.go
+./error_posix.go
+./exec.go
+./exec_posix.go
+./exec_unix.go
+./executable.go
+./executable_procfs.go
+./file.go
+./file_open_unix.go
+./file_posix.go
+./file_unix.go
+./getwd.go
+./path.go
+./path_unix.go
+./pipe2_unix.go
+./proc.go
+./rawconn.go
+./removeall_at.go
+./stat.go
+./stat_linux.go
+./stat_unix.go
+./sticky_notbsd.go
+./sys.go
+./sys_linux.go
+./sys_unix.go
+./tempfile.go
+./types.go
+./types_unix.go
+./wait_waitid.go
+./zero_copy_linux.go
diff --git a/.cell-installs/xdg-cache/go-build/42/4223e85d01dea2f1f6839cecfc8a84f7df3e0a973738e6c0e8e7a5d94e1f261d-a b/.cell-installs/xdg-cache/go-build/42/4223e85d01dea2f1f6839cecfc8a84f7df3e0a973738e6c0e8e7a5d94e1f261d-a
new file mode 100644
index 0000000..e309792
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/42/4223e85d01dea2f1f6839cecfc8a84f7df3e0a973738e6c0e8e7a5d94e1f261d-a
@@ -0,0 +1 @@
+v1 4223e85d01dea2f1f6839cecfc8a84f7df3e0a973738e6c0e8e7a5d94e1f261d 4b3edc628fed89c7cd65f6db01d0adfe201a8541efe010a73fac75208876b73b                  270  1787953153953164618
diff --git a/.cell-installs/xdg-cache/go-build/42/42331f8b0c5e71b976c9135f3520b2d77dd8e01231fae305932375b1f92f0859-a b/.cell-installs/xdg-cache/go-build/42/42331f8b0c5e71b976c9135f3520b2d77dd8e01231fae305932375b1f92f0859-a
new file mode 100644
index 0000000..77c0790
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/42/42331f8b0c5e71b976c9135f3520b2d77dd8e01231fae305932375b1f92f0859-a
@@ -0,0 +1 @@
+v1 42331f8b0c5e71b976c9135f3520b2d77dd8e01231fae305932375b1f92f0859 beef32386f7973c3eb2ab5cf8f1ac6cc55625b591614c9ea482ab472d8a2a42d                   54  1787953569309269691
diff --git a/.cell-installs/xdg-cache/go-build/42/42814d21689788be40ab3428620dab2ba6d9a976b6fa72935536d3ec43fb0280-d b/.cell-installs/xdg-cache/go-build/42/42814d21689788be40ab3428620dab2ba6d9a976b6fa72935536d3ec43fb0280-d
new file mode 100644
index 0000000..ab52f0c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/42/42814d21689788be40ab3428620dab2ba6d9a976b6fa72935536d3ec43fb0280-d differ
diff --git a/.cell-installs/xdg-cache/go-build/42/42829b36ad63c2a5f8cb730c484709b0dc5177c2dcd46b15dd1bbd6ab9c005fa-a b/.cell-installs/xdg-cache/go-build/42/42829b36ad63c2a5f8cb730c484709b0dc5177c2dcd46b15dd1bbd6ab9c005fa-a
new file mode 100644
index 0000000..6ef9705
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/42/42829b36ad63c2a5f8cb730c484709b0dc5177c2dcd46b15dd1bbd6ab9c005fa-a
@@ -0,0 +1 @@
+v1 42829b36ad63c2a5f8cb730c484709b0dc5177c2dcd46b15dd1bbd6ab9c005fa d552b33626d29e82f002a3f54415f193a5dbb3c7b1234b53e46d2a4812c50def               614470  1787953569990740114
diff --git a/.cell-installs/xdg-cache/go-build/42/42c7b9899336757c626a97b38b9e75e2a6c06315d12d8c7c478b7cc8e94e7305-d b/.cell-installs/xdg-cache/go-build/42/42c7b9899336757c626a97b38b9e75e2a6c06315d12d8c7c478b7cc8e94e7305-d
new file mode 100644
index 0000000..2285de8
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/42/42c7b9899336757c626a97b38b9e75e2a6c06315d12d8c7c478b7cc8e94e7305-d differ
diff --git a/.cell-installs/xdg-cache/go-build/42/42fb2d9e37a305e0b111c0cd83685348de1a28db6a814dc8b547dd79b45751ed-d b/.cell-installs/xdg-cache/go-build/42/42fb2d9e37a305e0b111c0cd83685348de1a28db6a814dc8b547dd79b45751ed-d
new file mode 100644
index 0000000..bd1ef6c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/42/42fb2d9e37a305e0b111c0cd83685348de1a28db6a814dc8b547dd79b45751ed-d
@@ -0,0 +1,4 @@
+./crc32.go
+./crc32_amd64.go
+./crc32_generic.go
+./crc32_amd64.s
diff --git a/.cell-installs/xdg-cache/go-build/43/4305425cfac95e1b8918654af191c71b9d21d4add86950a35742bce6c80d1f72-a b/.cell-installs/xdg-cache/go-build/43/4305425cfac95e1b8918654af191c71b9d21d4add86950a35742bce6c80d1f72-a
new file mode 100644
index 0000000..9fd6eeb
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/43/4305425cfac95e1b8918654af191c71b9d21d4add86950a35742bce6c80d1f72-a
@@ -0,0 +1 @@
+v1 4305425cfac95e1b8918654af191c71b9d21d4add86950a35742bce6c80d1f72 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569908427425
diff --git a/.cell-installs/xdg-cache/go-build/43/434e26b82091625cbcf810b85463e5ace56fbdc0810c86c69b0e6ba2a0f692c3-d b/.cell-installs/xdg-cache/go-build/43/434e26b82091625cbcf810b85463e5ace56fbdc0810c86c69b0e6ba2a0f692c3-d
new file mode 100644
index 0000000..eee0039
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/43/434e26b82091625cbcf810b85463e5ace56fbdc0810c86c69b0e6ba2a0f692c3-d
@@ -0,0 +1,4 @@
+./doc.go
+./signal.go
+./signal_unix.go
+./sig.s
diff --git a/.cell-installs/xdg-cache/go-build/43/4378aff0fc2711012aff605e8832606cd8ba67a5230e844873652c27d539c5f8-d b/.cell-installs/xdg-cache/go-build/43/4378aff0fc2711012aff605e8832606cd8ba67a5230e844873652c27d539c5f8-d
new file mode 100644
index 0000000..4571469
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/43/4378aff0fc2711012aff605e8832606cd8ba67a5230e844873652c27d539c5f8-d differ
diff --git a/.cell-installs/xdg-cache/go-build/43/43b103f82213e82437d62a528ec46ca8cdb6cba15131b88566562cdf9191d9f7-a b/.cell-installs/xdg-cache/go-build/43/43b103f82213e82437d62a528ec46ca8cdb6cba15131b88566562cdf9191d9f7-a
new file mode 100644
index 0000000..ea84f19
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/43/43b103f82213e82437d62a528ec46ca8cdb6cba15131b88566562cdf9191d9f7-a
@@ -0,0 +1 @@
+v1 43b103f82213e82437d62a528ec46ca8cdb6cba15131b88566562cdf9191d9f7 d40e3d104d81d256c7a33c0feecdb2e57e6835346cef267147d73ebb97feff95                  318  1787953569691722479
diff --git a/.cell-installs/xdg-cache/go-build/43/43c4af69dd2bd389aaaaeac1f3b9e24a849a2d0ab7c7f16dfbfad17ddf53d486-d b/.cell-installs/xdg-cache/go-build/43/43c4af69dd2bd389aaaaeac1f3b9e24a849a2d0ab7c7f16dfbfad17ddf53d486-d
new file mode 100644
index 0000000..b567be3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/43/43c4af69dd2bd389aaaaeac1f3b9e24a849a2d0ab7c7f16dfbfad17ddf53d486-d
@@ -0,0 +1,3 @@
+./bits.go
+./bits_errors.go
+./bits_tables.go
diff --git a/.cell-installs/xdg-cache/go-build/44/445aef4ac858ea51c41319209be0586bae34453c25d9d42f93d15af814de64e8-d b/.cell-installs/xdg-cache/go-build/44/445aef4ac858ea51c41319209be0586bae34453c25d9d42f93d15af814de64e8-d
new file mode 100644
index 0000000..e95467a
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/44/445aef4ac858ea51c41319209be0586bae34453c25d9d42f93d15af814de64e8-d differ
diff --git a/.cell-installs/xdg-cache/go-build/44/44a80de6835d70a5eccd8ffa3945f67e1bbddacfbe55ab1f520ddf94e22773e5-d b/.cell-installs/xdg-cache/go-build/44/44a80de6835d70a5eccd8ffa3945f67e1bbddacfbe55ab1f520ddf94e22773e5-d
new file mode 100644
index 0000000..d0fc7c4
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/44/44a80de6835d70a5eccd8ffa3945f67e1bbddacfbe55ab1f520ddf94e22773e5-d
@@ -0,0 +1,3 @@
+./exec.go
+./exec_unix.go
+./lp_unix.go
diff --git a/.cell-installs/xdg-cache/go-build/45/45b6233b87f2419d27b749bb1f151af9377e75152342c9339c0054196b3a06a9-a b/.cell-installs/xdg-cache/go-build/45/45b6233b87f2419d27b749bb1f151af9377e75152342c9339c0054196b3a06a9-a
new file mode 100644
index 0000000..a28a450
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/45/45b6233b87f2419d27b749bb1f151af9377e75152342c9339c0054196b3a06a9-a
@@ -0,0 +1 @@
+v1 45b6233b87f2419d27b749bb1f151af9377e75152342c9339c0054196b3a06a9 ebc608743758e879c3f560d024471ea55a11abb749e0611efebcefc11fc1d663                 1595  1787953771565953792
diff --git a/.cell-installs/xdg-cache/go-build/45/45d54b39c1c2e53bb2318b90999d5164a6642b13a3bf87e1086480981a6f6797-a b/.cell-installs/xdg-cache/go-build/45/45d54b39c1c2e53bb2318b90999d5164a6642b13a3bf87e1086480981a6f6797-a
new file mode 100644
index 0000000..e80251e
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/45/45d54b39c1c2e53bb2318b90999d5164a6642b13a3bf87e1086480981a6f6797-a
@@ -0,0 +1 @@
+v1 45d54b39c1c2e53bb2318b90999d5164a6642b13a3bf87e1086480981a6f6797 5b12f9d3838d0f7b318d30272ca62be05b008bb171ff171590bd86539a89aa61                 2695  1787953153943132435
diff --git a/.cell-installs/xdg-cache/go-build/46/46a65602b2f1a724b1d27169766dae76b2a217f50c9f3ea0db64c0dfc6fd51be-d b/.cell-installs/xdg-cache/go-build/46/46a65602b2f1a724b1d27169766dae76b2a217f50c9f3ea0db64c0dfc6fd51be-d
new file mode 100644
index 0000000..111cf77
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/46/46a65602b2f1a724b1d27169766dae76b2a217f50c9f3ea0db64c0dfc6fd51be-d differ
diff --git a/.cell-installs/xdg-cache/go-build/47/4706468f6c7c25d0a62f2f90f03c18fadd0b9c340dac0e87c1b16527ee2947e6-a b/.cell-installs/xdg-cache/go-build/47/4706468f6c7c25d0a62f2f90f03c18fadd0b9c340dac0e87c1b16527ee2947e6-a
new file mode 100644
index 0000000..33ecd23
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/47/4706468f6c7c25d0a62f2f90f03c18fadd0b9c340dac0e87c1b16527ee2947e6-a
@@ -0,0 +1 @@
+v1 4706468f6c7c25d0a62f2f90f03c18fadd0b9c340dac0e87c1b16527ee2947e6 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569918932704
diff --git a/.cell-installs/xdg-cache/go-build/47/473320d2a47bb060dd37e54b70c47990bdeb6fbc5aa1c99d754990bb333df9c6-a b/.cell-installs/xdg-cache/go-build/47/473320d2a47bb060dd37e54b70c47990bdeb6fbc5aa1c99d754990bb333df9c6-a
new file mode 100644
index 0000000..2384778
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/47/473320d2a47bb060dd37e54b70c47990bdeb6fbc5aa1c99d754990bb333df9c6-a
@@ -0,0 +1 @@
+v1 473320d2a47bb060dd37e54b70c47990bdeb6fbc5aa1c99d754990bb333df9c6 e1cdd23c9f7eb506ae94b8ee061010759f0d5afd514322827b4d71bad7ff5f9a               759074  1787953570112598580
diff --git a/.cell-installs/xdg-cache/go-build/47/4757b6edef36d068d59d363e1eaebed83f9834f586468afec7f4e510f8953752-d b/.cell-installs/xdg-cache/go-build/47/4757b6edef36d068d59d363e1eaebed83f9834f586468afec7f4e510f8953752-d
new file mode 100644
index 0000000..8129658
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/47/4757b6edef36d068d59d363e1eaebed83f9834f586468afec7f4e510f8953752-d
@@ -0,0 +1,3 @@
+./defs_linux_amd64.go
+./syscall_linux.go
+./asm_linux_amd64.s
diff --git a/.cell-installs/xdg-cache/go-build/47/47bb65f8521da52cbac5918c9685c6780bce98fdae9142b4019e5128f36dab9a-a b/.cell-installs/xdg-cache/go-build/47/47bb65f8521da52cbac5918c9685c6780bce98fdae9142b4019e5128f36dab9a-a
new file mode 100644
index 0000000..6574803
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/47/47bb65f8521da52cbac5918c9685c6780bce98fdae9142b4019e5128f36dab9a-a
@@ -0,0 +1 @@
+v1 47bb65f8521da52cbac5918c9685c6780bce98fdae9142b4019e5128f36dab9a 373b941e4336a16485c9f03c7ad55914b794cd15c18d4959e6e93447b1f79bc3                 1256  1787953170154570333
diff --git a/.cell-installs/xdg-cache/go-build/47/47c32ef72c3b58b1c58f35f6dd81eac08cb492b7d5f936ec49d3aa2805687efe-a b/.cell-installs/xdg-cache/go-build/47/47c32ef72c3b58b1c58f35f6dd81eac08cb492b7d5f936ec49d3aa2805687efe-a
new file mode 100644
index 0000000..60fc4bd
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/47/47c32ef72c3b58b1c58f35f6dd81eac08cb492b7d5f936ec49d3aa2805687efe-a
@@ -0,0 +1 @@
+v1 47c32ef72c3b58b1c58f35f6dd81eac08cb492b7d5f936ec49d3aa2805687efe e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568935502281
diff --git a/.cell-installs/xdg-cache/go-build/47/47ca5f743267f9ce20acca61d1cef5a2decb9ca3b17d19f59f01a590b70e8b5c-d b/.cell-installs/xdg-cache/go-build/47/47ca5f743267f9ce20acca61d1cef5a2decb9ca3b17d19f59f01a590b70e8b5c-d
new file mode 100644
index 0000000..a6db68d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/47/47ca5f743267f9ce20acca61d1cef5a2decb9ca3b17d19f59f01a590b70e8b5c-d
@@ -0,0 +1 @@
+./sort.go
diff --git a/.cell-installs/xdg-cache/go-build/47/47dd74b5b2db30b011a3f22a6d7aece646d6a3cc6d1e9c639562bd54f4c5dc6e-a b/.cell-installs/xdg-cache/go-build/47/47dd74b5b2db30b011a3f22a6d7aece646d6a3cc6d1e9c639562bd54f4c5dc6e-a
new file mode 100644
index 0000000..d288ee1
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/47/47dd74b5b2db30b011a3f22a6d7aece646d6a3cc6d1e9c639562bd54f4c5dc6e-a
@@ -0,0 +1 @@
+v1 47dd74b5b2db30b011a3f22a6d7aece646d6a3cc6d1e9c639562bd54f4c5dc6e a634d4fc589457eb6b84a32e327e18a482cb690c000536a8bc6bdfebd7fc69b3              1896206  1787953569488965849
diff --git a/.cell-installs/xdg-cache/go-build/47/47ecbdef62303d40929fb70a681e370c5cc16c3cb3e7486f00bd2ed3431f9520-d b/.cell-installs/xdg-cache/go-build/47/47ecbdef62303d40929fb70a681e370c5cc16c3cb3e7486f00bd2ed3431f9520-d
new file mode 100644
index 0000000..0e68d04
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/47/47ecbdef62303d40929fb70a681e370c5cc16c3cb3e7486f00bd2ed3431f9520-d differ
diff --git a/.cell-installs/xdg-cache/go-build/48/4814f658ff78f1bd25654e38aa525b043246523f0e4c93bc785ca91edf232750-d b/.cell-installs/xdg-cache/go-build/48/4814f658ff78f1bd25654e38aa525b043246523f0e4c93bc785ca91edf232750-d
new file mode 100644
index 0000000..e07af2e
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/48/4814f658ff78f1bd25654e38aa525b043246523f0e4c93bc785ca91edf232750-d differ
diff --git a/.cell-installs/xdg-cache/go-build/48/484e1143b1d2c0780cf6e2916495e0da42f5d8aa11c046ea4645fddd48162365-a b/.cell-installs/xdg-cache/go-build/48/484e1143b1d2c0780cf6e2916495e0da42f5d8aa11c046ea4645fddd48162365-a
new file mode 100644
index 0000000..52962b7
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/48/484e1143b1d2c0780cf6e2916495e0da42f5d8aa11c046ea4645fddd48162365-a
@@ -0,0 +1 @@
+v1 484e1143b1d2c0780cf6e2916495e0da42f5d8aa11c046ea4645fddd48162365 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569687775395
diff --git a/.cell-installs/xdg-cache/go-build/48/4851cd1a6a2902eec82a2d44a74b7c9a22b858e41b55299c47291bf076d59c14-d b/.cell-installs/xdg-cache/go-build/48/4851cd1a6a2902eec82a2d44a74b7c9a22b858e41b55299c47291bf076d59c14-d
new file mode 100644
index 0000000..2c6c51c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/48/4851cd1a6a2902eec82a2d44a74b7c9a22b858e41b55299c47291bf076d59c14-d differ
diff --git a/.cell-installs/xdg-cache/go-build/48/48a1f12a3a3e65fab18ed5268204c2487969251b881135a2e1acee55111b3799-a b/.cell-installs/xdg-cache/go-build/48/48a1f12a3a3e65fab18ed5268204c2487969251b881135a2e1acee55111b3799-a
new file mode 100644
index 0000000..c625d61
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/48/48a1f12a3a3e65fab18ed5268204c2487969251b881135a2e1acee55111b3799-a
@@ -0,0 +1 @@
+v1 48a1f12a3a3e65fab18ed5268204c2487969251b881135a2e1acee55111b3799 e9b258c07795d46311fe15ade947865f3b41d08453c938ead71e3b2227bc7e79                  770  1787953567721780315
diff --git a/.cell-installs/xdg-cache/go-build/48/48dcffd6203ee541a43fb13c5d947b744abd96043f264561e19caefe279967a8-d b/.cell-installs/xdg-cache/go-build/48/48dcffd6203ee541a43fb13c5d947b744abd96043f264561e19caefe279967a8-d
new file mode 100644
index 0000000..9b19c5e
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/48/48dcffd6203ee541a43fb13c5d947b744abd96043f264561e19caefe279967a8-d
@@ -0,0 +1 @@
+./utf16.go
diff --git a/.cell-installs/xdg-cache/go-build/48/48e5a225cb5eb484b8e9b6847181888b9973b801defbca27d13d104edf3dc3bd-a b/.cell-installs/xdg-cache/go-build/48/48e5a225cb5eb484b8e9b6847181888b9973b801defbca27d13d104edf3dc3bd-a
new file mode 100644
index 0000000..c2d22db
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/48/48e5a225cb5eb484b8e9b6847181888b9973b801defbca27d13d104edf3dc3bd-a
@@ -0,0 +1 @@
+v1 48e5a225cb5eb484b8e9b6847181888b9973b801defbca27d13d104edf3dc3bd 1357a859103dc38781f79d277f194e53fce4ffbea054d6543af474d52e5a3d5e              1228760  1787953570067427138
diff --git a/.cell-installs/xdg-cache/go-build/49/493346c865965ecfaaa25fcd88a4e9e2ec34f1ecd2d02af655f7cacb94ae7b21-a b/.cell-installs/xdg-cache/go-build/49/493346c865965ecfaaa25fcd88a4e9e2ec34f1ecd2d02af655f7cacb94ae7b21-a
new file mode 100644
index 0000000..ade8de3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/49/493346c865965ecfaaa25fcd88a4e9e2ec34f1ecd2d02af655f7cacb94ae7b21-a
@@ -0,0 +1 @@
+v1 493346c865965ecfaaa25fcd88a4e9e2ec34f1ecd2d02af655f7cacb94ae7b21 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570316541633
diff --git a/.cell-installs/xdg-cache/go-build/49/497333517d98b32b15db31cc9449aa9d90cdc91f111414bd2c409917a22afb80-a b/.cell-installs/xdg-cache/go-build/49/497333517d98b32b15db31cc9449aa9d90cdc91f111414bd2c409917a22afb80-a
new file mode 100644
index 0000000..9a35540
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/49/497333517d98b32b15db31cc9449aa9d90cdc91f111414bd2c409917a22afb80-a
@@ -0,0 +1 @@
+v1 497333517d98b32b15db31cc9449aa9d90cdc91f111414bd2c409917a22afb80 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569577281225
diff --git a/.cell-installs/xdg-cache/go-build/49/498f31e234285772b475e288f548de235ef6acdb7fff2d1773b5185566469705-a b/.cell-installs/xdg-cache/go-build/49/498f31e234285772b475e288f548de235ef6acdb7fff2d1773b5185566469705-a
new file mode 100644
index 0000000..25a46d6
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/49/498f31e234285772b475e288f548de235ef6acdb7fff2d1773b5185566469705-a
@@ -0,0 +1 @@
+v1 498f31e234285772b475e288f548de235ef6acdb7fff2d1773b5185566469705 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569740112138
diff --git a/.cell-installs/xdg-cache/go-build/49/49a34b181a765c694d50b98936ef72a21756da53b11b40354362ec81f504cfad-d b/.cell-installs/xdg-cache/go-build/49/49a34b181a765c694d50b98936ef72a21756da53b11b40354362ec81f504cfad-d
new file mode 100644
index 0000000..25a6d23
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/49/49a34b181a765c694d50b98936ef72a21756da53b11b40354362ec81f504cfad-d differ
diff --git a/.cell-installs/xdg-cache/go-build/49/49f23af4b354ee2b3fbed2f69f95aed9638c0f7adb14e65d2b17a75d95a0b0df-d b/.cell-installs/xdg-cache/go-build/49/49f23af4b354ee2b3fbed2f69f95aed9638c0f7adb14e65d2b17a75d95a0b0df-d
new file mode 100644
index 0000000..2b8ac87
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/49/49f23af4b354ee2b3fbed2f69f95aed9638c0f7adb14e65d2b17a75d95a0b0df-d differ
diff --git a/.cell-installs/xdg-cache/go-build/4a/4a0961d8b432bbe09d3c1e3c2354dc13eedb25edcd16f8a778a99186ae04ad50-a b/.cell-installs/xdg-cache/go-build/4a/4a0961d8b432bbe09d3c1e3c2354dc13eedb25edcd16f8a778a99186ae04ad50-a
new file mode 100644
index 0000000..51df892
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/4a/4a0961d8b432bbe09d3c1e3c2354dc13eedb25edcd16f8a778a99186ae04ad50-a
@@ -0,0 +1 @@
+v1 4a0961d8b432bbe09d3c1e3c2354dc13eedb25edcd16f8a778a99186ae04ad50 77c974c0d2d56cf26cd4ef503b306ebc90b5cdd4a6569cd9166a36517f102941                 4491  1787953153950476506
diff --git a/.cell-installs/xdg-cache/go-build/4a/4a16a1243c9abc68554201809770c6af0942b4fd8c4c66ff112a129d27c0cfea-d b/.cell-installs/xdg-cache/go-build/4a/4a16a1243c9abc68554201809770c6af0942b4fd8c4c66ff112a129d27c0cfea-d
new file mode 100644
index 0000000..acc670d
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/4a/4a16a1243c9abc68554201809770c6af0942b4fd8c4c66ff112a129d27c0cfea-d differ
diff --git a/.cell-installs/xdg-cache/go-build/4a/4a26379acc5101a0a9b2486c9670be74cb9b68670dac30d770cd706aa8af7c79-a b/.cell-installs/xdg-cache/go-build/4a/4a26379acc5101a0a9b2486c9670be74cb9b68670dac30d770cd706aa8af7c79-a
new file mode 100644
index 0000000..5d80965
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/4a/4a26379acc5101a0a9b2486c9670be74cb9b68670dac30d770cd706aa8af7c79-a
@@ -0,0 +1 @@
+v1 4a26379acc5101a0a9b2486c9670be74cb9b68670dac30d770cd706aa8af7c79 fab7958ae09ecf8ca65edcbcf701c21846b4d3dd473a4af32011f721849957bd                 6452  1787953170164009178
diff --git a/.cell-installs/xdg-cache/go-build/4a/4a4288ce5a63b8806941a0f50b8c1c0fa3d772fee95d39f58274eedee9bed535-d b/.cell-installs/xdg-cache/go-build/4a/4a4288ce5a63b8806941a0f50b8c1c0fa3d772fee95d39f58274eedee9bed535-d
new file mode 100644
index 0000000..087da8a
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/4a/4a4288ce5a63b8806941a0f50b8c1c0fa3d772fee95d39f58274eedee9bed535-d differ
diff --git a/.cell-installs/xdg-cache/go-build/4a/4a7b1ba075ba5c2d9f7b3dc5e4b547aaa311c89f4bd555b0b6c51c61eb75b6f8-a b/.cell-installs/xdg-cache/go-build/4a/4a7b1ba075ba5c2d9f7b3dc5e4b547aaa311c89f4bd555b0b6c51c61eb75b6f8-a
new file mode 100644
index 0000000..3174887
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/4a/4a7b1ba075ba5c2d9f7b3dc5e4b547aaa311c89f4bd555b0b6c51c61eb75b6f8-a
@@ -0,0 +1 @@
+v1 4a7b1ba075ba5c2d9f7b3dc5e4b547aaa311c89f4bd555b0b6c51c61eb75b6f8 fc40abd0343f9a80c5b3dab549574858d22f9d70262ed2d3a847fdb54e3e303e                   12  1787953568823290205
diff --git a/.cell-installs/xdg-cache/go-build/4a/4ab6715c35869f46022c6fedfcbe4c8eed3a83a3a4535dd66547a77ed92096a2-a b/.cell-installs/xdg-cache/go-build/4a/4ab6715c35869f46022c6fedfcbe4c8eed3a83a3a4535dd66547a77ed92096a2-a
new file mode 100644
index 0000000..ee783b0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/4a/4ab6715c35869f46022c6fedfcbe4c8eed3a83a3a4535dd66547a77ed92096a2-a
@@ -0,0 +1 @@
+v1 4ab6715c35869f46022c6fedfcbe4c8eed3a83a3a4535dd66547a77ed92096a2 1c47c8e9f9315b11ad7f879a8d2127b31aa20f398771a16f6041d609bd14d90a                  271  1787953170162217994
diff --git a/.cell-installs/xdg-cache/go-build/4b/4b3edc628fed89c7cd65f6db01d0adfe201a8541efe010a73fac75208876b73b-d b/.cell-installs/xdg-cache/go-build/4b/4b3edc628fed89c7cd65f6db01d0adfe201a8541efe010a73fac75208876b73b-d
new file mode 100644
index 0000000..8efe1e2
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/4b/4b3edc628fed89c7cd65f6db01d0adfe201a8541efe010a73fac75208876b73b-d differ
diff --git a/.cell-installs/xdg-cache/go-build/4b/4b4f9a0534b1fb3049a4febd92ed872477f39fff75c2216c672fe9eed912d400-d b/.cell-installs/xdg-cache/go-build/4b/4b4f9a0534b1fb3049a4febd92ed872477f39fff75c2216c672fe9eed912d400-d
new file mode 100644
index 0000000..e0e07c8
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/4b/4b4f9a0534b1fb3049a4febd92ed872477f39fff75c2216c672fe9eed912d400-d differ
diff --git a/.cell-installs/xdg-cache/go-build/4b/4bdbf9107270ebd94059c5b067e9690b5d4259648f863f9e2b846ef18e74f838-a b/.cell-installs/xdg-cache/go-build/4b/4bdbf9107270ebd94059c5b067e9690b5d4259648f863f9e2b846ef18e74f838-a
new file mode 100644
index 0000000..84c2373
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/4b/4bdbf9107270ebd94059c5b067e9690b5d4259648f863f9e2b846ef18e74f838-a
@@ -0,0 +1 @@
+v1 4bdbf9107270ebd94059c5b067e9690b5d4259648f863f9e2b846ef18e74f838 b5bc52004771c06ad330d202035fa8e1571f1a3a4a04c902b889af0e689032e2                  968  1787953170144977601
diff --git a/.cell-installs/xdg-cache/go-build/4b/4bfc6b5dbe3c90da63dc8151eac801c94a8de9111cf5b51e2a6b990c1ac09a4c-a b/.cell-installs/xdg-cache/go-build/4b/4bfc6b5dbe3c90da63dc8151eac801c94a8de9111cf5b51e2a6b990c1ac09a4c-a
new file mode 100644
index 0000000..c8f6bc0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/4b/4bfc6b5dbe3c90da63dc8151eac801c94a8de9111cf5b51e2a6b990c1ac09a4c-a
@@ -0,0 +1 @@
+v1 4bfc6b5dbe3c90da63dc8151eac801c94a8de9111cf5b51e2a6b990c1ac09a4c 6818d99da9b815ac534970e1daaab3109cf54e892202bb3f4957d33fcf770359                 9775  1787953153964307269
diff --git a/.cell-installs/xdg-cache/go-build/4c/4c023099bc53af80b4c357e643699fe350e05430997454c39beb11cf524f5b5a-a b/.cell-installs/xdg-cache/go-build/4c/4c023099bc53af80b4c357e643699fe350e05430997454c39beb11cf524f5b5a-a
new file mode 100644
index 0000000..98cbb7a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/4c/4c023099bc53af80b4c357e643699fe350e05430997454c39beb11cf524f5b5a-a
@@ -0,0 +1 @@
+v1 4c023099bc53af80b4c357e643699fe350e05430997454c39beb11cf524f5b5a 73da4db3a27e0f68902f139a590f8484b0a39682f98c26cb13b262f49474eeb8                   10  1787953567785560991
diff --git a/.cell-installs/xdg-cache/go-build/4c/4c1b2479da623e2b7aa0407542682fcf90ef0350eca3ea003dbe6f35f92acf1c-a b/.cell-installs/xdg-cache/go-build/4c/4c1b2479da623e2b7aa0407542682fcf90ef0350eca3ea003dbe6f35f92acf1c-a
new file mode 100644
index 0000000..68456db
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/4c/4c1b2479da623e2b7aa0407542682fcf90ef0350eca3ea003dbe6f35f92acf1c-a
@@ -0,0 +1 @@
+v1 4c1b2479da623e2b7aa0407542682fcf90ef0350eca3ea003dbe6f35f92acf1c 548412be6c2fa9fe639250ac67403551ca71df87ee24d7c2365be7d58c9b7740                  945  1787953153953967112
diff --git a/.cell-installs/xdg-cache/go-build/4c/4c9eef2e380ab5ea31cd52cbdf624a37e76c5c78f78fc4be30b1164587a33eef-d b/.cell-installs/xdg-cache/go-build/4c/4c9eef2e380ab5ea31cd52cbdf624a37e76c5c78f78fc4be30b1164587a33eef-d
new file mode 100644
index 0000000..b42bb55
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/4c/4c9eef2e380ab5ea31cd52cbdf624a37e76c5c78f78fc4be30b1164587a33eef-d differ
diff --git a/.cell-installs/xdg-cache/go-build/4c/4cc4ed3b930d55c0ef57cae3403b59d651741564e99d4f74049749b527cedda1-a b/.cell-installs/xdg-cache/go-build/4c/4cc4ed3b930d55c0ef57cae3403b59d651741564e99d4f74049749b527cedda1-a
new file mode 100644
index 0000000..5bb9c8f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/4c/4cc4ed3b930d55c0ef57cae3403b59d651741564e99d4f74049749b527cedda1-a
@@ -0,0 +1 @@
+v1 4cc4ed3b930d55c0ef57cae3403b59d651741564e99d4f74049749b527cedda1 08b5e0dab7d3087a33f63125a3e698d348aea5d157f099d2a4a331dccc410266                   86  1787953569094117040
diff --git a/.cell-installs/xdg-cache/go-build/4d/4d460f037624d239e0d4f6911f11fbedbb046b55caa9a87d6ea94703d291780a-a b/.cell-installs/xdg-cache/go-build/4d/4d460f037624d239e0d4f6911f11fbedbb046b55caa9a87d6ea94703d291780a-a
new file mode 100644
index 0000000..bcdad50
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/4d/4d460f037624d239e0d4f6911f11fbedbb046b55caa9a87d6ea94703d291780a-a
@@ -0,0 +1 @@
+v1 4d460f037624d239e0d4f6911f11fbedbb046b55caa9a87d6ea94703d291780a c9e606d004cc52dc1cdab23e1466ec305f9e53462c296e6eb2c3ee4595d0718f                  195  1787953569702886749
diff --git a/.cell-installs/xdg-cache/go-build/4d/4df10a6e3571de8c90873ea31a3e01baadaa299f31d68967a8a573d8a888d77b-a b/.cell-installs/xdg-cache/go-build/4d/4df10a6e3571de8c90873ea31a3e01baadaa299f31d68967a8a573d8a888d77b-a
new file mode 100644
index 0000000..2e49196
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/4d/4df10a6e3571de8c90873ea31a3e01baadaa299f31d68967a8a573d8a888d77b-a
@@ -0,0 +1 @@
+v1 4df10a6e3571de8c90873ea31a3e01baadaa299f31d68967a8a573d8a888d77b f6d91d76db966cea547adb9cb5a26b4203179ecf21b2a1ccba376c9d1db2778e                   87  1787953568855365091
diff --git a/.cell-installs/xdg-cache/go-build/4e/4e4081b3c32089363cc74392db61c99ed3128e41d256915076ab37f07c68f3c5-a b/.cell-installs/xdg-cache/go-build/4e/4e4081b3c32089363cc74392db61c99ed3128e41d256915076ab37f07c68f3c5-a
new file mode 100644
index 0000000..d07a97a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/4e/4e4081b3c32089363cc74392db61c99ed3128e41d256915076ab37f07c68f3c5-a
@@ -0,0 +1 @@
+v1 4e4081b3c32089363cc74392db61c99ed3128e41d256915076ab37f07c68f3c5 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569928247951
diff --git a/.cell-installs/xdg-cache/go-build/4e/4ec4413d53544228023e789286389ca84af5a2c8e1c541534fd672509202338b-a b/.cell-installs/xdg-cache/go-build/4e/4ec4413d53544228023e789286389ca84af5a2c8e1c541534fd672509202338b-a
new file mode 100644
index 0000000..67b1c1d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/4e/4ec4413d53544228023e789286389ca84af5a2c8e1c541534fd672509202338b-a
@@ -0,0 +1 @@
+v1 4ec4413d53544228023e789286389ca84af5a2c8e1c541534fd672509202338b e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570263492118
diff --git a/.cell-installs/xdg-cache/go-build/4e/4ee0ec2fa7ea747c77142ca91915e78ebc7620de7417f60ab014c2d48ad09f74-d b/.cell-installs/xdg-cache/go-build/4e/4ee0ec2fa7ea747c77142ca91915e78ebc7620de7417f60ab014c2d48ad09f74-d
new file mode 100644
index 0000000..57e7baa
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/4e/4ee0ec2fa7ea747c77142ca91915e78ebc7620de7417f60ab014c2d48ad09f74-d differ
diff --git a/.cell-installs/xdg-cache/go-build/4e/4eff77e14b030f3dba2e0a2381df1bff0ca2b357f596235ada7c0c413350f181-a b/.cell-installs/xdg-cache/go-build/4e/4eff77e14b030f3dba2e0a2381df1bff0ca2b357f596235ada7c0c413350f181-a
new file mode 100644
index 0000000..df47f5b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/4e/4eff77e14b030f3dba2e0a2381df1bff0ca2b357f596235ada7c0c413350f181-a
@@ -0,0 +1 @@
+v1 4eff77e14b030f3dba2e0a2381df1bff0ca2b357f596235ada7c0c413350f181 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569578536408
diff --git a/.cell-installs/xdg-cache/go-build/4f/4f0a1cbd0732ddb0f2cd16cddb6213a7d87772abae7704778c6946bfee08c34a-a b/.cell-installs/xdg-cache/go-build/4f/4f0a1cbd0732ddb0f2cd16cddb6213a7d87772abae7704778c6946bfee08c34a-a
new file mode 100644
index 0000000..571bacf
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/4f/4f0a1cbd0732ddb0f2cd16cddb6213a7d87772abae7704778c6946bfee08c34a-a
@@ -0,0 +1 @@
+v1 4f0a1cbd0732ddb0f2cd16cddb6213a7d87772abae7704778c6946bfee08c34a e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568811353791
diff --git a/.cell-installs/xdg-cache/go-build/4f/4f2747b213efa0bd02edc39923a7a870030ea1f9da72e058c50aa65c23e47074-a b/.cell-installs/xdg-cache/go-build/4f/4f2747b213efa0bd02edc39923a7a870030ea1f9da72e058c50aa65c23e47074-a
new file mode 100644
index 0000000..b3743c9
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/4f/4f2747b213efa0bd02edc39923a7a870030ea1f9da72e058c50aa65c23e47074-a
@@ -0,0 +1 @@
+v1 4f2747b213efa0bd02edc39923a7a870030ea1f9da72e058c50aa65c23e47074 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569988290716
diff --git a/.cell-installs/xdg-cache/go-build/4f/4f810f99d802ae3d07a1091ed6f79ea384dbd3d3c5a9e4fa243db3ea1935dd18-d b/.cell-installs/xdg-cache/go-build/4f/4f810f99d802ae3d07a1091ed6f79ea384dbd3d3c5a9e4fa243db3ea1935dd18-d
new file mode 100644
index 0000000..4e04902
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/4f/4f810f99d802ae3d07a1091ed6f79ea384dbd3d3c5a9e4fa243db3ea1935dd18-d differ
diff --git a/.cell-installs/xdg-cache/go-build/4f/4fdef5eec62ef7544c783097d502bea876208318cf5b0158a020b48f31da5dbb-a b/.cell-installs/xdg-cache/go-build/4f/4fdef5eec62ef7544c783097d502bea876208318cf5b0158a020b48f31da5dbb-a
new file mode 100644
index 0000000..7636835
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/4f/4fdef5eec62ef7544c783097d502bea876208318cf5b0158a020b48f31da5dbb-a
@@ -0,0 +1 @@
+v1 4fdef5eec62ef7544c783097d502bea876208318cf5b0158a020b48f31da5dbb ab0f58cf35f72da4d8ab558cc55d55364b36bb8a1fb81b5e662633da3b165305                 6858  1787953569871292370
diff --git a/.cell-installs/xdg-cache/go-build/50/5001c9415508922c2ff88168fcdc05d7c7f55d4efffa0a2103bbc77515a1afcf-a b/.cell-installs/xdg-cache/go-build/50/5001c9415508922c2ff88168fcdc05d7c7f55d4efffa0a2103bbc77515a1afcf-a
new file mode 100644
index 0000000..7c82db8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/50/5001c9415508922c2ff88168fcdc05d7c7f55d4efffa0a2103bbc77515a1afcf-a
@@ -0,0 +1 @@
+v1 5001c9415508922c2ff88168fcdc05d7c7f55d4efffa0a2103bbc77515a1afcf e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569918842992
diff --git a/.cell-installs/xdg-cache/go-build/50/5053a2e9eab5ebe8949421fa803383d4c1ecc84998623948d2a07235a7f29069-d b/.cell-installs/xdg-cache/go-build/50/5053a2e9eab5ebe8949421fa803383d4c1ecc84998623948d2a07235a7f29069-d
new file mode 100644
index 0000000..4204ba3
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/50/5053a2e9eab5ebe8949421fa803383d4c1ecc84998623948d2a07235a7f29069-d differ
diff --git a/.cell-installs/xdg-cache/go-build/50/50faaeaff9e101a1dfcc379308effc66b43b18cc370e71a3de592ff5f8f072b8-a b/.cell-installs/xdg-cache/go-build/50/50faaeaff9e101a1dfcc379308effc66b43b18cc370e71a3de592ff5f8f072b8-a
new file mode 100644
index 0000000..55e37a9
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/50/50faaeaff9e101a1dfcc379308effc66b43b18cc370e71a3de592ff5f8f072b8-a
@@ -0,0 +1 @@
+v1 50faaeaff9e101a1dfcc379308effc66b43b18cc370e71a3de592ff5f8f072b8 9f5f2c2c50b41b8721dd1b53ba287892ef72a421639f9e6f909b7be7699a7230                 2926  1787953771532821395
diff --git a/.cell-installs/xdg-cache/go-build/51/51716356f949a91162c6b941fe8b8bc95ea51d30ba4c674f540b4712ce5a94ae-d b/.cell-installs/xdg-cache/go-build/51/51716356f949a91162c6b941fe8b8bc95ea51d30ba4c674f540b4712ce5a94ae-d
new file mode 100644
index 0000000..1bf2927
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/51/51716356f949a91162c6b941fe8b8bc95ea51d30ba4c674f540b4712ce5a94ae-d differ
diff --git a/.cell-installs/xdg-cache/go-build/51/518410455dd37f05430c91270fb1ace103ec679b41a5b42486c0eeeb42bc3e8f-a b/.cell-installs/xdg-cache/go-build/51/518410455dd37f05430c91270fb1ace103ec679b41a5b42486c0eeeb42bc3e8f-a
new file mode 100644
index 0000000..7152490
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/51/518410455dd37f05430c91270fb1ace103ec679b41a5b42486c0eeeb42bc3e8f-a
@@ -0,0 +1 @@
+v1 518410455dd37f05430c91270fb1ace103ec679b41a5b42486c0eeeb42bc3e8f c4d15e9eaeab19516ec43aa4b60e459ce49daf55600559e3750a28941e894062                 2980  1787953153952118462
diff --git a/.cell-installs/xdg-cache/go-build/51/51d296765d022f6bd8bb3dbd0888da27daf5e880649e7c1ef1eaa0bb6001412e-a b/.cell-installs/xdg-cache/go-build/51/51d296765d022f6bd8bb3dbd0888da27daf5e880649e7c1ef1eaa0bb6001412e-a
new file mode 100644
index 0000000..16fe027
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/51/51d296765d022f6bd8bb3dbd0888da27daf5e880649e7c1ef1eaa0bb6001412e-a
@@ -0,0 +1 @@
+v1 51d296765d022f6bd8bb3dbd0888da27daf5e880649e7c1ef1eaa0bb6001412e d75ed97c20e1aa4718e332a366eeb08d5d54cd114711701963c70897dc0fab55                  209  1787953170161704593
diff --git a/.cell-installs/xdg-cache/go-build/51/51fd94afe5b08a240bdc9487fb1a0a80c17ca03d9c69bfad6ac62b378f4473fc-d b/.cell-installs/xdg-cache/go-build/51/51fd94afe5b08a240bdc9487fb1a0a80c17ca03d9c69bfad6ac62b378f4473fc-d
new file mode 100644
index 0000000..2ed7838
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/51/51fd94afe5b08a240bdc9487fb1a0a80c17ca03d9c69bfad6ac62b378f4473fc-d differ
diff --git a/.cell-installs/xdg-cache/go-build/52/523a2db0e203596ad2b687e0a3c6234d803c9b657bed72adbee46e8a8848c540-a b/.cell-installs/xdg-cache/go-build/52/523a2db0e203596ad2b687e0a3c6234d803c9b657bed72adbee46e8a8848c540-a
new file mode 100644
index 0000000..37c9dce
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/52/523a2db0e203596ad2b687e0a3c6234d803c9b657bed72adbee46e8a8848c540-a
@@ -0,0 +1 @@
+v1 523a2db0e203596ad2b687e0a3c6234d803c9b657bed72adbee46e8a8848c540 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569905792630
diff --git a/.cell-installs/xdg-cache/go-build/52/529c6dd5d2f770445e9521f9ee43fc70155a5a814ed51cf5cba12169a0009306-a b/.cell-installs/xdg-cache/go-build/52/529c6dd5d2f770445e9521f9ee43fc70155a5a814ed51cf5cba12169a0009306-a
new file mode 100644
index 0000000..db0d1df
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/52/529c6dd5d2f770445e9521f9ee43fc70155a5a814ed51cf5cba12169a0009306-a
@@ -0,0 +1 @@
+v1 529c6dd5d2f770445e9521f9ee43fc70155a5a814ed51cf5cba12169a0009306 9158a5d9d6442aa12fdb3adf3cb106077aa3a24f7dbd6de70df331cb63b4ed5c                  135  1787953569358780977
diff --git a/.cell-installs/xdg-cache/go-build/52/52b60edbd0fed54064daf07a15b87f78a645aa74efe3c949ca72799335e73c4f-d b/.cell-installs/xdg-cache/go-build/52/52b60edbd0fed54064daf07a15b87f78a645aa74efe3c949ca72799335e73c4f-d
new file mode 100644
index 0000000..0362d9c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/52/52b60edbd0fed54064daf07a15b87f78a645aa74efe3c949ca72799335e73c4f-d differ
diff --git a/.cell-installs/xdg-cache/go-build/52/52b77398a7b06551ca29ef91a10469fc1f1e6e98780a63a1e8662ffbce5acbde-a b/.cell-installs/xdg-cache/go-build/52/52b77398a7b06551ca29ef91a10469fc1f1e6e98780a63a1e8662ffbce5acbde-a
new file mode 100644
index 0000000..7552c3a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/52/52b77398a7b06551ca29ef91a10469fc1f1e6e98780a63a1e8662ffbce5acbde-a
@@ -0,0 +1 @@
+v1 52b77398a7b06551ca29ef91a10469fc1f1e6e98780a63a1e8662ffbce5acbde e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568786159863
diff --git a/.cell-installs/xdg-cache/go-build/53/53281c07dfc0c7ec2cdde8676bb78aeaed34dd1be7213149c04ecad7a6d6b114-a b/.cell-installs/xdg-cache/go-build/53/53281c07dfc0c7ec2cdde8676bb78aeaed34dd1be7213149c04ecad7a6d6b114-a
new file mode 100644
index 0000000..75e33aa
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/53/53281c07dfc0c7ec2cdde8676bb78aeaed34dd1be7213149c04ecad7a6d6b114-a
@@ -0,0 +1 @@
+v1 53281c07dfc0c7ec2cdde8676bb78aeaed34dd1be7213149c04ecad7a6d6b114 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569681112700
diff --git a/.cell-installs/xdg-cache/go-build/53/53712ef3fad2b57b1ed184ffca55f08d259fa5f87b052cb5b28b86ab69069c5f-d b/.cell-installs/xdg-cache/go-build/53/53712ef3fad2b57b1ed184ffca55f08d259fa5f87b052cb5b28b86ab69069c5f-d
new file mode 100644
index 0000000..705999c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/53/53712ef3fad2b57b1ed184ffca55f08d259fa5f87b052cb5b28b86ab69069c5f-d
@@ -0,0 +1,4 @@
+./constant_time.go
+./xor.go
+./xor_amd64.go
+./xor_amd64.s
diff --git a/.cell-installs/xdg-cache/go-build/53/538c92bc3645b6804d0a3d28277fe4f05a5724715bfa6b5cf8a61cd05853dd7f-d b/.cell-installs/xdg-cache/go-build/53/538c92bc3645b6804d0a3d28277fe4f05a5724715bfa6b5cf8a61cd05853dd7f-d
new file mode 100644
index 0000000..cd6c52a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/53/538c92bc3645b6804d0a3d28277fe4f05a5724715bfa6b5cf8a61cd05853dd7f-d
@@ -0,0 +1,3 @@
+./binary.go
+./native_endian_little.go
+./varint.go
diff --git a/.cell-installs/xdg-cache/go-build/53/538f244abf55e4ae4d54306a5f454374febfd5f5506fc06e63facbdde62bb8e5-a b/.cell-installs/xdg-cache/go-build/53/538f244abf55e4ae4d54306a5f454374febfd5f5506fc06e63facbdde62bb8e5-a
new file mode 100644
index 0000000..862c375
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/53/538f244abf55e4ae4d54306a5f454374febfd5f5506fc06e63facbdde62bb8e5-a
@@ -0,0 +1 @@
+v1 538f244abf55e4ae4d54306a5f454374febfd5f5506fc06e63facbdde62bb8e5 51fd94afe5b08a240bdc9487fb1a0a80c17ca03d9c69bfad6ac62b378f4473fc                 1020  1787953771571574321
diff --git a/.cell-installs/xdg-cache/go-build/53/53907b21a5ca54cb1302daa288723f0de8b14a35762318ff4bbd72ec7a16788f-a b/.cell-installs/xdg-cache/go-build/53/53907b21a5ca54cb1302daa288723f0de8b14a35762318ff4bbd72ec7a16788f-a
new file mode 100644
index 0000000..f0db002
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/53/53907b21a5ca54cb1302daa288723f0de8b14a35762318ff4bbd72ec7a16788f-a
@@ -0,0 +1 @@
+v1 53907b21a5ca54cb1302daa288723f0de8b14a35762318ff4bbd72ec7a16788f e32abf2ee1120847e9dffe170372d53207aefc72a1c5fc5bd60757c075c91d0f                 2149  1787953771530483666
diff --git a/.cell-installs/xdg-cache/go-build/54/548412be6c2fa9fe639250ac67403551ca71df87ee24d7c2365be7d58c9b7740-d b/.cell-installs/xdg-cache/go-build/54/548412be6c2fa9fe639250ac67403551ca71df87ee24d7c2365be7d58c9b7740-d
new file mode 100644
index 0000000..edfe019
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/54/548412be6c2fa9fe639250ac67403551ca71df87ee24d7c2365be7d58c9b7740-d differ
diff --git a/.cell-installs/xdg-cache/go-build/54/54d3b01966fb7a0a04821fa99ad7db66a2b28976939b87a25da1b2b3ba5a50b6-d b/.cell-installs/xdg-cache/go-build/54/54d3b01966fb7a0a04821fa99ad7db66a2b28976939b87a25da1b2b3ba5a50b6-d
new file mode 100644
index 0000000..2ae6d48
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/54/54d3b01966fb7a0a04821fa99ad7db66a2b28976939b87a25da1b2b3ba5a50b6-d differ
diff --git a/.cell-installs/xdg-cache/go-build/55/550361217cf42fe8f1dceb7ee8e8ea53d82bc2e52196358c89f1779a8d31e5ad-a b/.cell-installs/xdg-cache/go-build/55/550361217cf42fe8f1dceb7ee8e8ea53d82bc2e52196358c89f1779a8d31e5ad-a
new file mode 100644
index 0000000..891d7cc
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/55/550361217cf42fe8f1dceb7ee8e8ea53d82bc2e52196358c89f1779a8d31e5ad-a
@@ -0,0 +1 @@
+v1 550361217cf42fe8f1dceb7ee8e8ea53d82bc2e52196358c89f1779a8d31e5ad e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569910096541
diff --git a/.cell-installs/xdg-cache/go-build/55/5569cac738075a06fb92a7b09e07977aa7c42a18c5fa0285c071ff090f424bcd-a b/.cell-installs/xdg-cache/go-build/55/5569cac738075a06fb92a7b09e07977aa7c42a18c5fa0285c071ff090f424bcd-a
new file mode 100644
index 0000000..ac223cb
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/55/5569cac738075a06fb92a7b09e07977aa7c42a18c5fa0285c071ff090f424bcd-a
@@ -0,0 +1 @@
+v1 5569cac738075a06fb92a7b09e07977aa7c42a18c5fa0285c071ff090f424bcd 8d7bccc341adffc5f99102eb7b04123879112979330b6daade5669edb602fd2d               128876  1787953569346939632
diff --git a/.cell-installs/xdg-cache/go-build/55/55838bd1ed0723a5c179042ebbeb16386b9829bd3faa017343275d9fc5538af7-a b/.cell-installs/xdg-cache/go-build/55/55838bd1ed0723a5c179042ebbeb16386b9829bd3faa017343275d9fc5538af7-a
new file mode 100644
index 0000000..0e39774
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/55/55838bd1ed0723a5c179042ebbeb16386b9829bd3faa017343275d9fc5538af7-a
@@ -0,0 +1 @@
+v1 55838bd1ed0723a5c179042ebbeb16386b9829bd3faa017343275d9fc5538af7 10b0709935bbdb5a308b97bf016d1e23cff5cf54085cee4ba61fdba366ee9a09                  144  1787953170151384832
diff --git a/.cell-installs/xdg-cache/go-build/55/55ed99b88a68cf5492e921dd2d214c388b23d9aace0d7e0d525e7e4778482f90-d b/.cell-installs/xdg-cache/go-build/55/55ed99b88a68cf5492e921dd2d214c388b23d9aace0d7e0d525e7e4778482f90-d
new file mode 100644
index 0000000..993a983
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/55/55ed99b88a68cf5492e921dd2d214c388b23d9aace0d7e0d525e7e4778482f90-d
@@ -0,0 +1,6 @@
+./search.go
+./slice.go
+./sort.go
+./sort_impl_go121.go
+./zsortfunc.go
+./zsortinterface.go
diff --git a/.cell-installs/xdg-cache/go-build/55/55fd549a896ae85852b40fcacf3c0910f9901da4676a91d9e64bcadaabfe8db6-a b/.cell-installs/xdg-cache/go-build/55/55fd549a896ae85852b40fcacf3c0910f9901da4676a91d9e64bcadaabfe8db6-a
new file mode 100644
index 0000000..86d341c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/55/55fd549a896ae85852b40fcacf3c0910f9901da4676a91d9e64bcadaabfe8db6-a
@@ -0,0 +1 @@
+v1 55fd549a896ae85852b40fcacf3c0910f9901da4676a91d9e64bcadaabfe8db6 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569918728189
diff --git a/.cell-installs/xdg-cache/go-build/56/5657913c2786abd10bd2bfd99861b5f00cc49a574825c603f4f6fd9186104db1-a b/.cell-installs/xdg-cache/go-build/56/5657913c2786abd10bd2bfd99861b5f00cc49a574825c603f4f6fd9186104db1-a
new file mode 100644
index 0000000..895b0fe
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/56/5657913c2786abd10bd2bfd99861b5f00cc49a574825c603f4f6fd9186104db1-a
@@ -0,0 +1 @@
+v1 5657913c2786abd10bd2bfd99861b5f00cc49a574825c603f4f6fd9186104db1 009d834f5adda1179ff374e289a408b508796d05177b99fa92c55fddbf130440                 4065  1787953153943591000
diff --git a/.cell-installs/xdg-cache/go-build/56/5698740c6f7be77c8f1ed3930c4ffdb34b98135a42deb3eccef52bd94bbde6f3-a b/.cell-installs/xdg-cache/go-build/56/5698740c6f7be77c8f1ed3930c4ffdb34b98135a42deb3eccef52bd94bbde6f3-a
new file mode 100644
index 0000000..9301ce5
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/56/5698740c6f7be77c8f1ed3930c4ffdb34b98135a42deb3eccef52bd94bbde6f3-a
@@ -0,0 +1 @@
+v1 5698740c6f7be77c8f1ed3930c4ffdb34b98135a42deb3eccef52bd94bbde6f3 44a80de6835d70a5eccd8ffa3945f67e1bbddacfbe55ab1f520ddf94e22773e5                   38  1787953569881845167
diff --git a/.cell-installs/xdg-cache/go-build/56/56e6a51653f2207ae2de540b8e72e47073c38247374fce78f7bc8be3f1f1b706-d b/.cell-installs/xdg-cache/go-build/56/56e6a51653f2207ae2de540b8e72e47073c38247374fce78f7bc8be3f1f1b706-d
new file mode 100644
index 0000000..11407c9
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/56/56e6a51653f2207ae2de540b8e72e47073c38247374fce78f7bc8be3f1f1b706-d differ
diff --git a/.cell-installs/xdg-cache/go-build/57/578586d15c0423bfb4145692871f6d950929b8f7e47d193a97031a7a973b58f6-d b/.cell-installs/xdg-cache/go-build/57/578586d15c0423bfb4145692871f6d950929b8f7e47d193a97031a7a973b58f6-d
new file mode 100644
index 0000000..09528b2
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/57/578586d15c0423bfb4145692871f6d950929b8f7e47d193a97031a7a973b58f6-d differ
diff --git a/.cell-installs/xdg-cache/go-build/57/5792ec264618e784a8a12d526a8340d411a37a6f004185b553736dca641dbfc2-a b/.cell-installs/xdg-cache/go-build/57/5792ec264618e784a8a12d526a8340d411a37a6f004185b553736dca641dbfc2-a
new file mode 100644
index 0000000..4dde5ec
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/57/5792ec264618e784a8a12d526a8340d411a37a6f004185b553736dca641dbfc2-a
@@ -0,0 +1 @@
+v1 5792ec264618e784a8a12d526a8340d411a37a6f004185b553736dca641dbfc2 6ecf6f7732403d515f4956a24dfe6b75b7dfe31d12a7cc3798e875e7be3cf382                22588  1787953569876187815
diff --git a/.cell-installs/xdg-cache/go-build/57/57ad9667795ffd4e8f36ea82ed0eae5752fb4872f1fd6bb6e9736d1575bc896e-a b/.cell-installs/xdg-cache/go-build/57/57ad9667795ffd4e8f36ea82ed0eae5752fb4872f1fd6bb6e9736d1575bc896e-a
new file mode 100644
index 0000000..fb6c3bc
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/57/57ad9667795ffd4e8f36ea82ed0eae5752fb4872f1fd6bb6e9736d1575bc896e-a
@@ -0,0 +1 @@
+v1 57ad9667795ffd4e8f36ea82ed0eae5752fb4872f1fd6bb6e9736d1575bc896e 4851cd1a6a2902eec82a2d44a74b7c9a22b858e41b55299c47291bf076d59c14                   56  1787953294989892284
diff --git a/.cell-installs/xdg-cache/go-build/58/58353caac093da847b29d3aa534bb8cbb4ba13d3cec4b88010cb171852493bc1-d b/.cell-installs/xdg-cache/go-build/58/58353caac093da847b29d3aa534bb8cbb4ba13d3cec4b88010cb171852493bc1-d
new file mode 100644
index 0000000..52c33af
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/58/58353caac093da847b29d3aa534bb8cbb4ba13d3cec4b88010cb171852493bc1-d differ
diff --git a/.cell-installs/xdg-cache/go-build/58/586c6e204f0b28bdff6580d514e9f9db57003e840490e0bfd3ca5e919310e799-a b/.cell-installs/xdg-cache/go-build/58/586c6e204f0b28bdff6580d514e9f9db57003e840490e0bfd3ca5e919310e799-a
new file mode 100644
index 0000000..9aabd48
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/58/586c6e204f0b28bdff6580d514e9f9db57003e840490e0bfd3ca5e919310e799-a
@@ -0,0 +1 @@
+v1 586c6e204f0b28bdff6580d514e9f9db57003e840490e0bfd3ca5e919310e799 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570263633954
diff --git a/.cell-installs/xdg-cache/go-build/58/588c48084dbb4254dc0295e690144b527f2e578bd5193a87b8b0ce6cff7fe834-a b/.cell-installs/xdg-cache/go-build/58/588c48084dbb4254dc0295e690144b527f2e578bd5193a87b8b0ce6cff7fe834-a
new file mode 100644
index 0000000..7dc2816
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/58/588c48084dbb4254dc0295e690144b527f2e578bd5193a87b8b0ce6cff7fe834-a
@@ -0,0 +1 @@
+v1 588c48084dbb4254dc0295e690144b527f2e578bd5193a87b8b0ce6cff7fe834 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569638934706
diff --git a/.cell-installs/xdg-cache/go-build/58/58dbd5877002af947bd055eac015fedce499bd27603c595c42308b2a3984f1b7-a b/.cell-installs/xdg-cache/go-build/58/58dbd5877002af947bd055eac015fedce499bd27603c595c42308b2a3984f1b7-a
new file mode 100644
index 0000000..a40d4ed
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/58/58dbd5877002af947bd055eac015fedce499bd27603c595c42308b2a3984f1b7-a
@@ -0,0 +1 @@
+v1 58dbd5877002af947bd055eac015fedce499bd27603c595c42308b2a3984f1b7 acc4505e9587e9679db61b5f25d204bb07ace206991f9a104a96cf73005eb12a                 3374  1787953567788017757
diff --git a/.cell-installs/xdg-cache/go-build/58/58f8cea9624751a69cfe44f95cecf02a235f3fb63c8388754e8b09b56ec72df8-a b/.cell-installs/xdg-cache/go-build/58/58f8cea9624751a69cfe44f95cecf02a235f3fb63c8388754e8b09b56ec72df8-a
new file mode 100644
index 0000000..26036c1
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/58/58f8cea9624751a69cfe44f95cecf02a235f3fb63c8388754e8b09b56ec72df8-a
@@ -0,0 +1 @@
+v1 58f8cea9624751a69cfe44f95cecf02a235f3fb63c8388754e8b09b56ec72df8 86abb8148fda71a53a76de023d8bda3cb92c9122ca659d36b3d99b40c576e9e7                 6626  1787953153953559500
diff --git a/.cell-installs/xdg-cache/go-build/59/5903650bb151a6bd894e8650c0df2e127e7a8f74703a8d3df53231655f303ce4-a b/.cell-installs/xdg-cache/go-build/59/5903650bb151a6bd894e8650c0df2e127e7a8f74703a8d3df53231655f303ce4-a
new file mode 100644
index 0000000..4588789
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/59/5903650bb151a6bd894e8650c0df2e127e7a8f74703a8d3df53231655f303ce4-a
@@ -0,0 +1 @@
+v1 5903650bb151a6bd894e8650c0df2e127e7a8f74703a8d3df53231655f303ce4 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569346222594
diff --git a/.cell-installs/xdg-cache/go-build/59/59038b9af1c4f063fc81537fc59a70f460870c5fd237c3920c1adc5b85cfad45-a b/.cell-installs/xdg-cache/go-build/59/59038b9af1c4f063fc81537fc59a70f460870c5fd237c3920c1adc5b85cfad45-a
new file mode 100644
index 0000000..59f2953
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/59/59038b9af1c4f063fc81537fc59a70f460870c5fd237c3920c1adc5b85cfad45-a
@@ -0,0 +1 @@
+v1 59038b9af1c4f063fc81537fc59a70f460870c5fd237c3920c1adc5b85cfad45 d961178bd75d17d668c32a31434a1717a8bbcbed439cc9ac88150132dc0472d4                 2261  1787953153949361212
diff --git a/.cell-installs/xdg-cache/go-build/59/59229d8edeb8d57d17a1d67878528ae803d7ebcfb88701c53206684ad0c3966e-a b/.cell-installs/xdg-cache/go-build/59/59229d8edeb8d57d17a1d67878528ae803d7ebcfb88701c53206684ad0c3966e-a
new file mode 100644
index 0000000..81b622d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/59/59229d8edeb8d57d17a1d67878528ae803d7ebcfb88701c53206684ad0c3966e-a
@@ -0,0 +1 @@
+v1 59229d8edeb8d57d17a1d67878528ae803d7ebcfb88701c53206684ad0c3966e 230182bc570593810c7d1832123a9ef21b52c4e5a4eefade6bfe670ab20ffe16                  295  1787953771556639161
diff --git a/.cell-installs/xdg-cache/go-build/59/5923bd9107d5115c8eee7cc9fe59eeb153c6086049202346df5f640a706253d5-d b/.cell-installs/xdg-cache/go-build/59/5923bd9107d5115c8eee7cc9fe59eeb153c6086049202346df5f640a706253d5-d
new file mode 100644
index 0000000..044b466
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/59/5923bd9107d5115c8eee7cc9fe59eeb153c6086049202346df5f640a706253d5-d differ
diff --git a/.cell-installs/xdg-cache/go-build/59/59f59be6794fc947564d97850c8c2b9df578d152fe88bc4ec6e99b5445a9cef6-a b/.cell-installs/xdg-cache/go-build/59/59f59be6794fc947564d97850c8c2b9df578d152fe88bc4ec6e99b5445a9cef6-a
new file mode 100644
index 0000000..a68d598
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/59/59f59be6794fc947564d97850c8c2b9df578d152fe88bc4ec6e99b5445a9cef6-a
@@ -0,0 +1 @@
+v1 59f59be6794fc947564d97850c8c2b9df578d152fe88bc4ec6e99b5445a9cef6 a4e62c872181b607dd4fdbbb026fdedb0ba76d725fbe4ff3daea15adee93898a                  567  1787953170180330111
diff --git a/.cell-installs/xdg-cache/go-build/5a/5a8d21b3342d4303a26b7cf0a7e35c94214f827cd9082e4a7f60681a5a0a0ce9-a b/.cell-installs/xdg-cache/go-build/5a/5a8d21b3342d4303a26b7cf0a7e35c94214f827cd9082e4a7f60681a5a0a0ce9-a
new file mode 100644
index 0000000..4760949
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/5a/5a8d21b3342d4303a26b7cf0a7e35c94214f827cd9082e4a7f60681a5a0a0ce9-a
@@ -0,0 +1 @@
+v1 5a8d21b3342d4303a26b7cf0a7e35c94214f827cd9082e4a7f60681a5a0a0ce9 b6eb2546f1e2539f2a9c298012b43caf467b7a33b0cee66fdb53c6c488ea1a4a                  628  1787953153930753123
diff --git a/.cell-installs/xdg-cache/go-build/5a/5a8d49adbb4525dab6a7ba29f1464bacdb5a659645a33ffbb9140df227d9df14-a b/.cell-installs/xdg-cache/go-build/5a/5a8d49adbb4525dab6a7ba29f1464bacdb5a659645a33ffbb9140df227d9df14-a
new file mode 100644
index 0000000..27241f3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/5a/5a8d49adbb4525dab6a7ba29f1464bacdb5a659645a33ffbb9140df227d9df14-a
@@ -0,0 +1 @@
+v1 5a8d49adbb4525dab6a7ba29f1464bacdb5a659645a33ffbb9140df227d9df14 704cd4b6348a76be744fa2e9d4f017a48bfc0111fe9bf62fba2f23b1ab5566ed                   98  1787953567785986555
diff --git a/.cell-installs/xdg-cache/go-build/5a/5aaca925b333793d9a4bbf8d1c51b8d0c8f7d5e4ef5b3c9415326193e8dbecfa-a b/.cell-installs/xdg-cache/go-build/5a/5aaca925b333793d9a4bbf8d1c51b8d0c8f7d5e4ef5b3c9415326193e8dbecfa-a
new file mode 100644
index 0000000..26e1ae0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/5a/5aaca925b333793d9a4bbf8d1c51b8d0c8f7d5e4ef5b3c9415326193e8dbecfa-a
@@ -0,0 +1 @@
+v1 5aaca925b333793d9a4bbf8d1c51b8d0c8f7d5e4ef5b3c9415326193e8dbecfa 00dedcbaf5dd36c49447863279d4bf0649eb1838d56074e8076fc688dff92fca                   13  1787953568808629510
diff --git a/.cell-installs/xdg-cache/go-build/5a/5af8bb4e3f743174849dd3fb1709b9cd3ecb48cbbac41d4c7f1e80c62d8d7a7c-d b/.cell-installs/xdg-cache/go-build/5a/5af8bb4e3f743174849dd3fb1709b9cd3ecb48cbbac41d4c7f1e80c62d8d7a7c-d
new file mode 100644
index 0000000..7f4d6a2
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/5a/5af8bb4e3f743174849dd3fb1709b9cd3ecb48cbbac41d4c7f1e80c62d8d7a7c-d differ
diff --git a/.cell-installs/xdg-cache/go-build/5b/5b12f9d3838d0f7b318d30272ca62be05b008bb171ff171590bd86539a89aa61-d b/.cell-installs/xdg-cache/go-build/5b/5b12f9d3838d0f7b318d30272ca62be05b008bb171ff171590bd86539a89aa61-d
new file mode 100644
index 0000000..a56c07f
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/5b/5b12f9d3838d0f7b318d30272ca62be05b008bb171ff171590bd86539a89aa61-d differ
diff --git a/.cell-installs/xdg-cache/go-build/5b/5bc3176f5f663199617f39e2b43f0e31deb31fa3fdbf2cf7df700964c861438f-d b/.cell-installs/xdg-cache/go-build/5b/5bc3176f5f663199617f39e2b43f0e31deb31fa3fdbf2cf7df700964c861438f-d
new file mode 100644
index 0000000..4611fe3
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/5b/5bc3176f5f663199617f39e2b43f0e31deb31fa3fdbf2cf7df700964c861438f-d differ
diff --git a/.cell-installs/xdg-cache/go-build/5b/5bdc54d77bedcfdb99dbea0ea5f7f03c16ef490b6018bb76e9f275d132092c56-d b/.cell-installs/xdg-cache/go-build/5b/5bdc54d77bedcfdb99dbea0ea5f7f03c16ef490b6018bb76e9f275d132092c56-d
new file mode 100644
index 0000000..867609e
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/5b/5bdc54d77bedcfdb99dbea0ea5f7f03c16ef490b6018bb76e9f275d132092c56-d differ
diff --git a/.cell-installs/xdg-cache/go-build/5c/5c3da9b34dfddd8c87523f59e7d8ed31a37954a01b54edc7a26328ec952ddcce-d b/.cell-installs/xdg-cache/go-build/5c/5c3da9b34dfddd8c87523f59e7d8ed31a37954a01b54edc7a26328ec952ddcce-d
new file mode 100644
index 0000000..052dadb
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/5c/5c3da9b34dfddd8c87523f59e7d8ed31a37954a01b54edc7a26328ec952ddcce-d differ
diff --git a/.cell-installs/xdg-cache/go-build/5c/5cb1ae0eb2ab5f5a2821acbdb5c23496d9100b46095454c480ad8eb1464b117c-a b/.cell-installs/xdg-cache/go-build/5c/5cb1ae0eb2ab5f5a2821acbdb5c23496d9100b46095454c480ad8eb1464b117c-a
new file mode 100644
index 0000000..47b6088
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/5c/5cb1ae0eb2ab5f5a2821acbdb5c23496d9100b46095454c480ad8eb1464b117c-a
@@ -0,0 +1 @@
+v1 5cb1ae0eb2ab5f5a2821acbdb5c23496d9100b46095454c480ad8eb1464b117c 53712ef3fad2b57b1ed184ffca55f08d259fa5f87b052cb5b28b86ab69069c5f                   57  1787953569867830529
diff --git a/.cell-installs/xdg-cache/go-build/5c/5cb52b19fb74026997442aed74cfdbff560e13ca31c6fdb754d4e4eec040234e-d b/.cell-installs/xdg-cache/go-build/5c/5cb52b19fb74026997442aed74cfdbff560e13ca31c6fdb754d4e4eec040234e-d
new file mode 100644
index 0000000..1f938b8
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/5c/5cb52b19fb74026997442aed74cfdbff560e13ca31c6fdb754d4e4eec040234e-d differ
diff --git a/.cell-installs/xdg-cache/go-build/5c/5cd099f573ff613dadf03cea2d808962fe3df16bc4ab9b7b257e9052a2aa9264-d b/.cell-installs/xdg-cache/go-build/5c/5cd099f573ff613dadf03cea2d808962fe3df16bc4ab9b7b257e9052a2aa9264-d
new file mode 100644
index 0000000..5cbf388
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/5c/5cd099f573ff613dadf03cea2d808962fe3df16bc4ab9b7b257e9052a2aa9264-d differ
diff --git a/.cell-installs/xdg-cache/go-build/5d/5d7e116e83e92695c1c08224b9ab0d1821b6676414a239bdb9a9c0833e86f92d-a b/.cell-installs/xdg-cache/go-build/5d/5d7e116e83e92695c1c08224b9ab0d1821b6676414a239bdb9a9c0833e86f92d-a
new file mode 100644
index 0000000..59a8b08
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/5d/5d7e116e83e92695c1c08224b9ab0d1821b6676414a239bdb9a9c0833e86f92d-a
@@ -0,0 +1 @@
+v1 5d7e116e83e92695c1c08224b9ab0d1821b6676414a239bdb9a9c0833e86f92d 737802c136163f53e2d12c17d6fd5d4f03922763f552a2de21f4f2a62d73af2c                   40  1787953569882033796
diff --git a/.cell-installs/xdg-cache/go-build/5d/5df029a2173210584908fae37b35e6605988eb59bca557c8a2c081f02cd1d00f-a b/.cell-installs/xdg-cache/go-build/5d/5df029a2173210584908fae37b35e6605988eb59bca557c8a2c081f02cd1d00f-a
new file mode 100644
index 0000000..21b3eae
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/5d/5df029a2173210584908fae37b35e6605988eb59bca557c8a2c081f02cd1d00f-a
@@ -0,0 +1 @@
+v1 5df029a2173210584908fae37b35e6605988eb59bca557c8a2c081f02cd1d00f 82c5b94429bd84416b09a42ccc3283ac72321240b0ad12b9686840c6fbb0fc15                  530  1787953170161145466
diff --git a/.cell-installs/xdg-cache/go-build/5e/5e5909e60e3af49c74ec1a96e171b764adca6487adf82c785850e33f9bc76242-a b/.cell-installs/xdg-cache/go-build/5e/5e5909e60e3af49c74ec1a96e171b764adca6487adf82c785850e33f9bc76242-a
new file mode 100644
index 0000000..e39fb29
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/5e/5e5909e60e3af49c74ec1a96e171b764adca6487adf82c785850e33f9bc76242-a
@@ -0,0 +1 @@
+v1 5e5909e60e3af49c74ec1a96e171b764adca6487adf82c785850e33f9bc76242 75fb062c6c65fa531e2c3b3ce299c0ee5450b80e08f9e9fceaa825171d21ec5e               764934  1787953568812844995
diff --git a/.cell-installs/xdg-cache/go-build/5e/5e95a9d76db6a1e7a24d4a5145815e5808992b89e72f0e5ed8d1d6ac6335e509-a b/.cell-installs/xdg-cache/go-build/5e/5e95a9d76db6a1e7a24d4a5145815e5808992b89e72f0e5ed8d1d6ac6335e509-a
new file mode 100644
index 0000000..393348f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/5e/5e95a9d76db6a1e7a24d4a5145815e5808992b89e72f0e5ed8d1d6ac6335e509-a
@@ -0,0 +1 @@
+v1 5e95a9d76db6a1e7a24d4a5145815e5808992b89e72f0e5ed8d1d6ac6335e509 e619c61c469dd9fae2a5b01142f27f32632b38b877121eb3c910150ae4defd4d                 2149  1787953170155857480
diff --git a/.cell-installs/xdg-cache/go-build/5e/5ec58bb21842f92b85cf57378720c6ea34f6135207ba7b1017f516282624a02f-a b/.cell-installs/xdg-cache/go-build/5e/5ec58bb21842f92b85cf57378720c6ea34f6135207ba7b1017f516282624a02f-a
new file mode 100644
index 0000000..216c872
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/5e/5ec58bb21842f92b85cf57378720c6ea34f6135207ba7b1017f516282624a02f-a
@@ -0,0 +1 @@
+v1 5ec58bb21842f92b85cf57378720c6ea34f6135207ba7b1017f516282624a02f 4ee0ec2fa7ea747c77142ca91915e78ebc7620de7417f60ab014c2d48ad09f74                 2909  1787953170159065297
diff --git a/.cell-installs/xdg-cache/go-build/5e/5ede019b3b0699215b978af47d2a0979c3dee9c34f2518e7025bcbb42e547149-a b/.cell-installs/xdg-cache/go-build/5e/5ede019b3b0699215b978af47d2a0979c3dee9c34f2518e7025bcbb42e547149-a
new file mode 100644
index 0000000..a0c70f2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/5e/5ede019b3b0699215b978af47d2a0979c3dee9c34f2518e7025bcbb42e547149-a
@@ -0,0 +1 @@
+v1 5ede019b3b0699215b978af47d2a0979c3dee9c34f2518e7025bcbb42e547149 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569323556727
diff --git a/.cell-installs/xdg-cache/go-build/5e/5ee9f206959300a5e9eab1765401a044c44b550655df47e0fbf21a737818689c-a b/.cell-installs/xdg-cache/go-build/5e/5ee9f206959300a5e9eab1765401a044c44b550655df47e0fbf21a737818689c-a
new file mode 100644
index 0000000..1454e6b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/5e/5ee9f206959300a5e9eab1765401a044c44b550655df47e0fbf21a737818689c-a
@@ -0,0 +1 @@
+v1 5ee9f206959300a5e9eab1765401a044c44b550655df47e0fbf21a737818689c e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568826732986
diff --git a/.cell-installs/xdg-cache/go-build/5f/5f762883dae656ed2a9112fa67676bfcd31aabb3bb1c2a4681291e2097af54c3-a b/.cell-installs/xdg-cache/go-build/5f/5f762883dae656ed2a9112fa67676bfcd31aabb3bb1c2a4681291e2097af54c3-a
new file mode 100644
index 0000000..8068619
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/5f/5f762883dae656ed2a9112fa67676bfcd31aabb3bb1c2a4681291e2097af54c3-a
@@ -0,0 +1 @@
+v1 5f762883dae656ed2a9112fa67676bfcd31aabb3bb1c2a4681291e2097af54c3 9dbda35c4042bf5cc9685dc99baf39f8201faae252ea6c1ec517ebe186801318                 2768  1787953170147609891
diff --git a/.cell-installs/xdg-cache/go-build/5f/5fa2c6f752a30acf08d7deec598708802086c8ec873f4fefc3784efe65dee1a3-a b/.cell-installs/xdg-cache/go-build/5f/5fa2c6f752a30acf08d7deec598708802086c8ec873f4fefc3784efe65dee1a3-a
new file mode 100644
index 0000000..df71e6b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/5f/5fa2c6f752a30acf08d7deec598708802086c8ec873f4fefc3784efe65dee1a3-a
@@ -0,0 +1 @@
+v1 5fa2c6f752a30acf08d7deec598708802086c8ec873f4fefc3784efe65dee1a3 1278ae5aa98ae1693aa315ef8adc6ed50d8f7cd7878788f3dfa33011999d152f                  630  1787953771532665670
diff --git a/.cell-installs/xdg-cache/go-build/60/6006eff01694979a8d734713b4191806db03bc239f651e54c6f8cc718496b190-a b/.cell-installs/xdg-cache/go-build/60/6006eff01694979a8d734713b4191806db03bc239f651e54c6f8cc718496b190-a
new file mode 100644
index 0000000..40fa4ae
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/60/6006eff01694979a8d734713b4191806db03bc239f651e54c6f8cc718496b190-a
@@ -0,0 +1 @@
+v1 6006eff01694979a8d734713b4191806db03bc239f651e54c6f8cc718496b190 039e540d210c4508b11acd3c2eb9d2bf5bdbe356f090b9adab973815d9096130                 1066  1787953170156582729
diff --git a/.cell-installs/xdg-cache/go-build/60/6032fad5a4da6049c6af1f93024c8442779e0511ff8e884935f0eeede2f7d1ee-d b/.cell-installs/xdg-cache/go-build/60/6032fad5a4da6049c6af1f93024c8442779e0511ff8e884935f0eeede2f7d1ee-d
new file mode 100644
index 0000000..9a3c836
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/60/6032fad5a4da6049c6af1f93024c8442779e0511ff8e884935f0eeede2f7d1ee-d differ
diff --git a/.cell-installs/xdg-cache/go-build/60/60e68dc350ce65aba470df81aa4cc723fc163033ed43c7df8a6a762e886ea35c-a b/.cell-installs/xdg-cache/go-build/60/60e68dc350ce65aba470df81aa4cc723fc163033ed43c7df8a6a762e886ea35c-a
new file mode 100644
index 0000000..32b9345
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/60/60e68dc350ce65aba470df81aa4cc723fc163033ed43c7df8a6a762e886ea35c-a
@@ -0,0 +1 @@
+v1 60e68dc350ce65aba470df81aa4cc723fc163033ed43c7df8a6a762e886ea35c e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568822189616
diff --git a/.cell-installs/xdg-cache/go-build/61/6108a65a8a22a4978cd3c1f7d61f73a2944db05d66c5410e550498023ca203fd-d b/.cell-installs/xdg-cache/go-build/61/6108a65a8a22a4978cd3c1f7d61f73a2944db05d66c5410e550498023ca203fd-d
new file mode 100644
index 0000000..15496a2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/61/6108a65a8a22a4978cd3c1f7d61f73a2944db05d66c5410e550498023ca203fd-d
@@ -0,0 +1 @@
+./execenv_default.go
diff --git a/.cell-installs/xdg-cache/go-build/61/611333b6e0e9f3f6dd155b886debd7decd0cee8d533ce45e057452e54b50aaaa-d b/.cell-installs/xdg-cache/go-build/61/611333b6e0e9f3f6dd155b886debd7decd0cee8d533ce45e057452e54b50aaaa-d
new file mode 100644
index 0000000..1ab0a87
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/61/611333b6e0e9f3f6dd155b886debd7decd0cee8d533ce45e057452e54b50aaaa-d
@@ -0,0 +1,8 @@
+./compile.go
+./doc.go
+./op_string.go
+./parse.go
+./perl_groups.go
+./prog.go
+./regexp.go
+./simplify.go
diff --git a/.cell-installs/xdg-cache/go-build/62/6215f9904ee00d2d0ebf1cbf4b1a1d051cbf05d8741f115bb5c3588d284d56bd-a b/.cell-installs/xdg-cache/go-build/62/6215f9904ee00d2d0ebf1cbf4b1a1d051cbf05d8741f115bb5c3588d284d56bd-a
new file mode 100644
index 0000000..6dbe9ac
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/62/6215f9904ee00d2d0ebf1cbf4b1a1d051cbf05d8741f115bb5c3588d284d56bd-a
@@ -0,0 +1 @@
+v1 6215f9904ee00d2d0ebf1cbf4b1a1d051cbf05d8741f115bb5c3588d284d56bd e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569942703839
diff --git a/.cell-installs/xdg-cache/go-build/62/6227149457fe2478878adb919815d265106aee73f831b28d7e435e40ecce31ef-d b/.cell-installs/xdg-cache/go-build/62/6227149457fe2478878adb919815d265106aee73f831b28d7e435e40ecce31ef-d
new file mode 100644
index 0000000..881656e
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/62/6227149457fe2478878adb919815d265106aee73f831b28d7e435e40ecce31ef-d differ
diff --git a/.cell-installs/xdg-cache/go-build/62/624c621e9104f174ad6de12eaa55e9a8988d55d7df1d09a99d521eed04193dc0-a b/.cell-installs/xdg-cache/go-build/62/624c621e9104f174ad6de12eaa55e9a8988d55d7df1d09a99d521eed04193dc0-a
new file mode 100644
index 0000000..c049f5b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/62/624c621e9104f174ad6de12eaa55e9a8988d55d7df1d09a99d521eed04193dc0-a
@@ -0,0 +1 @@
+v1 624c621e9104f174ad6de12eaa55e9a8988d55d7df1d09a99d521eed04193dc0 059067f35f78410e458d26f0ed0b7c4e04e1f33bf394c455ac3b12438b11ce2b                 2403  1787953154050094661
diff --git a/.cell-installs/xdg-cache/go-build/62/62e8b37452f26dd8a1dba528fbcd2ee66f33251995190e1f8ff8b8455b81514a-a b/.cell-installs/xdg-cache/go-build/62/62e8b37452f26dd8a1dba528fbcd2ee66f33251995190e1f8ff8b8455b81514a-a
new file mode 100644
index 0000000..34fcef0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/62/62e8b37452f26dd8a1dba528fbcd2ee66f33251995190e1f8ff8b8455b81514a-a
@@ -0,0 +1 @@
+v1 62e8b37452f26dd8a1dba528fbcd2ee66f33251995190e1f8ff8b8455b81514a 9cd1c3bf0072aa0dccb28141565da849924ff9255f955bac9d3587a5da754b0b                   10  1787953570281226308
diff --git a/.cell-installs/xdg-cache/go-build/63/6302b731cb32e594ef6789f4bcfd001961e0304b0aa7d21df436911e3d8e02f1-a b/.cell-installs/xdg-cache/go-build/63/6302b731cb32e594ef6789f4bcfd001961e0304b0aa7d21df436911e3d8e02f1-a
new file mode 100644
index 0000000..fb73330
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/63/6302b731cb32e594ef6789f4bcfd001961e0304b0aa7d21df436911e3d8e02f1-a
@@ -0,0 +1 @@
+v1 6302b731cb32e594ef6789f4bcfd001961e0304b0aa7d21df436911e3d8e02f1 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567808838297
diff --git a/.cell-installs/xdg-cache/go-build/63/6348a653e43b283d86c7d3fff86833dd065166424e2ff3276432651b7b68d8f0-a b/.cell-installs/xdg-cache/go-build/63/6348a653e43b283d86c7d3fff86833dd065166424e2ff3276432651b7b68d8f0-a
new file mode 100644
index 0000000..3ff5bb8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/63/6348a653e43b283d86c7d3fff86833dd065166424e2ff3276432651b7b68d8f0-a
@@ -0,0 +1 @@
+v1 6348a653e43b283d86c7d3fff86833dd065166424e2ff3276432651b7b68d8f0 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568795745870
diff --git a/.cell-installs/xdg-cache/go-build/63/6353f35744a0a14dd5d52025f0f930e695b70bf3786e005cb542e804521549b7-d b/.cell-installs/xdg-cache/go-build/63/6353f35744a0a14dd5d52025f0f930e695b70bf3786e005cb542e804521549b7-d
new file mode 100644
index 0000000..3636ca7
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/63/6353f35744a0a14dd5d52025f0f930e695b70bf3786e005cb542e804521549b7-d
@@ -0,0 +1,3 @@
+./decimal.go
+./doc.go
+./integer.go
diff --git a/.cell-installs/xdg-cache/go-build/63/635c9be0decf027c1ed83106b67efec2b21df4a4f995f01ddd584d0a9a4dccfc-a b/.cell-installs/xdg-cache/go-build/63/635c9be0decf027c1ed83106b67efec2b21df4a4f995f01ddd584d0a9a4dccfc-a
new file mode 100644
index 0000000..34ca2b1
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/63/635c9be0decf027c1ed83106b67efec2b21df4a4f995f01ddd584d0a9a4dccfc-a
@@ -0,0 +1 @@
+v1 635c9be0decf027c1ed83106b67efec2b21df4a4f995f01ddd584d0a9a4dccfc a65f513e6a186ac963aad47cfb4e42df1c57dfbdc9c33bbbc0531f312f62745d                  782  1787953771565110169
diff --git a/.cell-installs/xdg-cache/go-build/63/63666c5ffc0987aa9477c6f21c153d8aa2a47f64b32900c0ad74303435b4e5cb-a b/.cell-installs/xdg-cache/go-build/63/63666c5ffc0987aa9477c6f21c153d8aa2a47f64b32900c0ad74303435b4e5cb-a
new file mode 100644
index 0000000..b08d400
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/63/63666c5ffc0987aa9477c6f21c153d8aa2a47f64b32900c0ad74303435b4e5cb-a
@@ -0,0 +1 @@
+v1 63666c5ffc0987aa9477c6f21c153d8aa2a47f64b32900c0ad74303435b4e5cb a9d0dae4cf16a3f4b93849c7da3619266c89245db550694737c6fd4854c073aa                 2944  1787953170163584624
diff --git a/.cell-installs/xdg-cache/go-build/63/6375748d9557a551364d25f7bcb3d2f22aa8f001270937221449c32bbcdde43f-d b/.cell-installs/xdg-cache/go-build/63/6375748d9557a551364d25f7bcb3d2f22aa8f001270937221449c32bbcdde43f-d
new file mode 100644
index 0000000..1f14b94
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/63/6375748d9557a551364d25f7bcb3d2f22aa8f001270937221449c32bbcdde43f-d differ
diff --git a/.cell-installs/xdg-cache/go-build/63/63f0e5464f4abfe4365e08aa9592f64c6b53264dc06f04b7f215abda985577d4-d b/.cell-installs/xdg-cache/go-build/63/63f0e5464f4abfe4365e08aa9592f64c6b53264dc06f04b7f215abda985577d4-d
new file mode 100644
index 0000000..ac98996
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/63/63f0e5464f4abfe4365e08aa9592f64c6b53264dc06f04b7f215abda985577d4-d differ
diff --git a/.cell-installs/xdg-cache/go-build/64/64642d0d1e5c0e9b3131b14f7d1a2a23b83ffafcdcce5abc11e2d962fd273dbe-a b/.cell-installs/xdg-cache/go-build/64/64642d0d1e5c0e9b3131b14f7d1a2a23b83ffafcdcce5abc11e2d962fd273dbe-a
new file mode 100644
index 0000000..7f8fbf9
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/64/64642d0d1e5c0e9b3131b14f7d1a2a23b83ffafcdcce5abc11e2d962fd273dbe-a
@@ -0,0 +1 @@
+v1 64642d0d1e5c0e9b3131b14f7d1a2a23b83ffafcdcce5abc11e2d962fd273dbe 88e230616ac1d082e1952afaf64a6ded7319217c1ac2b0c35794c4387381276e                  912  1787953153948443873
diff --git a/.cell-installs/xdg-cache/go-build/64/646e26125f65199141a9a465ec574360a59f47c8edb513a57be5373ecbf97903-d b/.cell-installs/xdg-cache/go-build/64/646e26125f65199141a9a465ec574360a59f47c8edb513a57be5373ecbf97903-d
new file mode 100644
index 0000000..5cbc276
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/64/646e26125f65199141a9a465ec574360a59f47c8edb513a57be5373ecbf97903-d differ
diff --git a/.cell-installs/xdg-cache/go-build/64/649b9b4c69e4dad0ab58183979d423b2b8dbf63adca906480fe18f04d8d95ae8-a b/.cell-installs/xdg-cache/go-build/64/649b9b4c69e4dad0ab58183979d423b2b8dbf63adca906480fe18f04d8d95ae8-a
new file mode 100644
index 0000000..cca4bf1
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/64/649b9b4c69e4dad0ab58183979d423b2b8dbf63adca906480fe18f04d8d95ae8-a
@@ -0,0 +1 @@
+v1 649b9b4c69e4dad0ab58183979d423b2b8dbf63adca906480fe18f04d8d95ae8 2c6eee214353b1e2363eb8b0b2fc3d18a009327898c7399f677cdf0af6df029b                  962  1787953570342005178
diff --git a/.cell-installs/xdg-cache/go-build/64/64b9e87fca56675f53fc8c3f031cca338924a5304ca054caf7b39efe99b06b57-d b/.cell-installs/xdg-cache/go-build/64/64b9e87fca56675f53fc8c3f031cca338924a5304ca054caf7b39efe99b06b57-d
new file mode 100644
index 0000000..b3f18f4
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/64/64b9e87fca56675f53fc8c3f031cca338924a5304ca054caf7b39efe99b06b57-d differ
diff --git a/.cell-installs/xdg-cache/go-build/64/64cfc81b5860e2fa8284baea827586063e3e3bc6972be2c2d895303571c944ef-a b/.cell-installs/xdg-cache/go-build/64/64cfc81b5860e2fa8284baea827586063e3e3bc6972be2c2d895303571c944ef-a
new file mode 100644
index 0000000..c883002
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/64/64cfc81b5860e2fa8284baea827586063e3e3bc6972be2c2d895303571c944ef-a
@@ -0,0 +1 @@
+v1 64cfc81b5860e2fa8284baea827586063e3e3bc6972be2c2d895303571c944ef 3effb769234dacb397c3e5f26bad37b8d9161cb124627446e51d1c3ab433e985                 3895  1787953771568226081
diff --git a/.cell-installs/xdg-cache/go-build/64/64e5d79c90992e570f03b10fd7c84b07cdeb734c9f8b95f4103090e038aafbf4-a b/.cell-installs/xdg-cache/go-build/64/64e5d79c90992e570f03b10fd7c84b07cdeb734c9f8b95f4103090e038aafbf4-a
new file mode 100644
index 0000000..77fa057
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/64/64e5d79c90992e570f03b10fd7c84b07cdeb734c9f8b95f4103090e038aafbf4-a
@@ -0,0 +1 @@
+v1 64e5d79c90992e570f03b10fd7c84b07cdeb734c9f8b95f4103090e038aafbf4 c6fce3e7622d1e337413abbd0789fc4032a4ffd99c4400cb811fadfa65d7b2b1                 1722  1787953170152386475
diff --git a/.cell-installs/xdg-cache/go-build/64/64f35a0d4962a7b524febc64efe58aac7d6140e25127d71a0b51e5d3a2cdf432-d b/.cell-installs/xdg-cache/go-build/64/64f35a0d4962a7b524febc64efe58aac7d6140e25127d71a0b51e5d3a2cdf432-d
new file mode 100644
index 0000000..866df94
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/64/64f35a0d4962a7b524febc64efe58aac7d6140e25127d71a0b51e5d3a2cdf432-d differ
diff --git a/.cell-installs/xdg-cache/go-build/65/65682fc4a853570ad6a6d612a32aa4f25db9fb86d8e5cfc79e651d73a0445cf3-d b/.cell-installs/xdg-cache/go-build/65/65682fc4a853570ad6a6d612a32aa4f25db9fb86d8e5cfc79e651d73a0445cf3-d
new file mode 100644
index 0000000..f6c82d1
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/65/65682fc4a853570ad6a6d612a32aa4f25db9fb86d8e5cfc79e651d73a0445cf3-d
@@ -0,0 +1,11 @@
+./cond.go
+./map.go
+./mutex.go
+./once.go
+./oncefunc.go
+./pool.go
+./poolqueue.go
+./runtime.go
+./runtime2.go
+./rwmutex.go
+./waitgroup.go
diff --git a/.cell-installs/xdg-cache/go-build/66/6673f85d4ca930185ebdd741a615fbf0fc26494c8657c9574baa94a74d257549-d b/.cell-installs/xdg-cache/go-build/66/6673f85d4ca930185ebdd741a615fbf0fc26494c8657c9574baa94a74d257549-d
new file mode 100644
index 0000000..06f326f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/66/6673f85d4ca930185ebdd741a615fbf0fc26494c8657c9574baa94a74d257549-d
@@ -0,0 +1,2 @@
+./doc.go
+./notboring.go
diff --git a/.cell-installs/xdg-cache/go-build/66/66b8f8f96de7a4b0b06c792689baf964d121a116dba01dd3a7b7ebdd2132cd01-d b/.cell-installs/xdg-cache/go-build/66/66b8f8f96de7a4b0b06c792689baf964d121a116dba01dd3a7b7ebdd2132cd01-d
new file mode 100644
index 0000000..6a1f7bf
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/66/66b8f8f96de7a4b0b06c792689baf964d121a116dba01dd3a7b7ebdd2132cd01-d differ
diff --git a/.cell-installs/xdg-cache/go-build/66/66bf25403e82d70e8e9c34bb5f5b7e84f6104be58b9a0dc8e822296f36c298f9-a b/.cell-installs/xdg-cache/go-build/66/66bf25403e82d70e8e9c34bb5f5b7e84f6104be58b9a0dc8e822296f36c298f9-a
new file mode 100644
index 0000000..3fa3c9d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/66/66bf25403e82d70e8e9c34bb5f5b7e84f6104be58b9a0dc8e822296f36c298f9-a
@@ -0,0 +1 @@
+v1 66bf25403e82d70e8e9c34bb5f5b7e84f6104be58b9a0dc8e822296f36c298f9 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569634781148
diff --git a/.cell-installs/xdg-cache/go-build/66/66fed055e17c771330829e4028cddd007076929443fa5caa24546193b0c06fdb-a b/.cell-installs/xdg-cache/go-build/66/66fed055e17c771330829e4028cddd007076929443fa5caa24546193b0c06fdb-a
new file mode 100644
index 0000000..30de7a3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/66/66fed055e17c771330829e4028cddd007076929443fa5caa24546193b0c06fdb-a
@@ -0,0 +1 @@
+v1 66fed055e17c771330829e4028cddd007076929443fa5caa24546193b0c06fdb b7bd3713e0bb26047d9d69b317202f0a5f9a14dbb722c18bd0a798c9be3366fd               439794  1787953568787324218
diff --git a/.cell-installs/xdg-cache/go-build/67/670c81db1b68ac74da78adbe0747ec16c63ed7057b46fe396aa7096609d7e5c6-d b/.cell-installs/xdg-cache/go-build/67/670c81db1b68ac74da78adbe0747ec16c63ed7057b46fe396aa7096609d7e5c6-d
new file mode 100644
index 0000000..37291b1
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/67/670c81db1b68ac74da78adbe0747ec16c63ed7057b46fe396aa7096609d7e5c6-d differ
diff --git a/.cell-installs/xdg-cache/go-build/67/67746ad597832bc4b47103cbe0d0fd90e2091657ee4948607b31bc9c4f1cbfd1-d b/.cell-installs/xdg-cache/go-build/67/67746ad597832bc4b47103cbe0d0fd90e2091657ee4948607b31bc9c4f1cbfd1-d
new file mode 100644
index 0000000..c4e92b8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/67/67746ad597832bc4b47103cbe0d0fd90e2091657ee4948607b31bc9c4f1cbfd1-d
@@ -0,0 +1,2 @@
+./bufio.go
+./scan.go
diff --git a/.cell-installs/xdg-cache/go-build/67/67b7f87a2737b08448fffad14847c8c35d451deb89273e69d4d778a0aaa54299-a b/.cell-installs/xdg-cache/go-build/67/67b7f87a2737b08448fffad14847c8c35d451deb89273e69d4d778a0aaa54299-a
new file mode 100644
index 0000000..aaf47b5
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/67/67b7f87a2737b08448fffad14847c8c35d451deb89273e69d4d778a0aaa54299-a
@@ -0,0 +1 @@
+v1 67b7f87a2737b08448fffad14847c8c35d451deb89273e69d4d778a0aaa54299 d6ae6443826e9de9b932d2cd3f5431a2c0823dbf8165f4ec13f7f2b1318edb26                 1685  1787953170145667700
diff --git a/.cell-installs/xdg-cache/go-build/67/67d91b7f7faf605f5b510b0cc956831ada0f4b6e54fc43eda49db42c2bda53f6-a b/.cell-installs/xdg-cache/go-build/67/67d91b7f7faf605f5b510b0cc956831ada0f4b6e54fc43eda49db42c2bda53f6-a
new file mode 100644
index 0000000..8f3f8c6
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/67/67d91b7f7faf605f5b510b0cc956831ada0f4b6e54fc43eda49db42c2bda53f6-a
@@ -0,0 +1 @@
+v1 67d91b7f7faf605f5b510b0cc956831ada0f4b6e54fc43eda49db42c2bda53f6 d7e3e47358719b37eb4f24ee2c6f9247104ae1f2e06f32f93d1f63842b4cbfdb                   88  1787953569236100206
diff --git a/.cell-installs/xdg-cache/go-build/67/67f1053980921c4b556e42ef4c3c13d1ae8580222f5beeeb157cf4aa7bbaa186-a b/.cell-installs/xdg-cache/go-build/67/67f1053980921c4b556e42ef4c3c13d1ae8580222f5beeeb157cf4aa7bbaa186-a
new file mode 100644
index 0000000..99684c3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/67/67f1053980921c4b556e42ef4c3c13d1ae8580222f5beeeb157cf4aa7bbaa186-a
@@ -0,0 +1 @@
+v1 67f1053980921c4b556e42ef4c3c13d1ae8580222f5beeeb157cf4aa7bbaa186 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570064902048
diff --git a/.cell-installs/xdg-cache/go-build/68/6818d99da9b815ac534970e1daaab3109cf54e892202bb3f4957d33fcf770359-d b/.cell-installs/xdg-cache/go-build/68/6818d99da9b815ac534970e1daaab3109cf54e892202bb3f4957d33fcf770359-d
new file mode 100644
index 0000000..b82bb1b
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/68/6818d99da9b815ac534970e1daaab3109cf54e892202bb3f4957d33fcf770359-d differ
diff --git a/.cell-installs/xdg-cache/go-build/68/6830dac86dee05a6dbd4c55db62a93907b678fe00431192ffa8ceda20421be86-a b/.cell-installs/xdg-cache/go-build/68/6830dac86dee05a6dbd4c55db62a93907b678fe00431192ffa8ceda20421be86-a
new file mode 100644
index 0000000..96bb839
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/68/6830dac86dee05a6dbd4c55db62a93907b678fe00431192ffa8ceda20421be86-a
@@ -0,0 +1 @@
+v1 6830dac86dee05a6dbd4c55db62a93907b678fe00431192ffa8ceda20421be86 646e26125f65199141a9a465ec574360a59f47c8edb513a57be5373ecbf97903                56982  1787953567797918725
diff --git a/.cell-installs/xdg-cache/go-build/68/68354b16ff2ed0d87c1153f267cf15bc5eb2d43863676df1bc5cede120d270e9-d b/.cell-installs/xdg-cache/go-build/68/68354b16ff2ed0d87c1153f267cf15bc5eb2d43863676df1bc5cede120d270e9-d
new file mode 100644
index 0000000..fc310db
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/68/68354b16ff2ed0d87c1153f267cf15bc5eb2d43863676df1bc5cede120d270e9-d differ
diff --git a/.cell-installs/xdg-cache/go-build/68/686797c345e8171997651eb3fc079e5fb249dda8cca0d028da2de8062d060381-d b/.cell-installs/xdg-cache/go-build/68/686797c345e8171997651eb3fc079e5fb249dda8cca0d028da2de8062d060381-d
new file mode 100644
index 0000000..422024f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/68/686797c345e8171997651eb3fc079e5fb249dda8cca0d028da2de8062d060381-d
@@ -0,0 +1,7 @@
+./cbc.go
+./cfb.go
+./cipher.go
+./ctr.go
+./gcm.go
+./io.go
+./ofb.go
diff --git a/.cell-installs/xdg-cache/go-build/69/6943d2abc9074c501160a0e693b19f6bad8ab2a6a99a45c512a436667b8ccbd8-a b/.cell-installs/xdg-cache/go-build/69/6943d2abc9074c501160a0e693b19f6bad8ab2a6a99a45c512a436667b8ccbd8-a
new file mode 100644
index 0000000..739bc61
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/69/6943d2abc9074c501160a0e693b19f6bad8ab2a6a99a45c512a436667b8ccbd8-a
@@ -0,0 +1 @@
+v1 6943d2abc9074c501160a0e693b19f6bad8ab2a6a99a45c512a436667b8ccbd8 f8cb3e1985e6d68a07c1b80638a1ff32f984373d283c002135ec4a32737c9444                 2668  1787953567730703981
diff --git a/.cell-installs/xdg-cache/go-build/69/694b508c297fff5a075529dc1d14c44ac2fa9ded62979fa9cc007e626a41f339-a b/.cell-installs/xdg-cache/go-build/69/694b508c297fff5a075529dc1d14c44ac2fa9ded62979fa9cc007e626a41f339-a
new file mode 100644
index 0000000..0ac92fe
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/69/694b508c297fff5a075529dc1d14c44ac2fa9ded62979fa9cc007e626a41f339-a
@@ -0,0 +1 @@
+v1 694b508c297fff5a075529dc1d14c44ac2fa9ded62979fa9cc007e626a41f339 f446a4f70cda2ea56a5a600109ff2f91c2af04bec3d821bf0b2634eb04e2197f                 2017  1787953771570241415
diff --git a/.cell-installs/xdg-cache/go-build/69/69a8a35487589134e88fae6e9944960fe39e95e6e490fe2cb639ab48aaa35094-d b/.cell-installs/xdg-cache/go-build/69/69a8a35487589134e88fae6e9944960fe39e95e6e490fe2cb639ab48aaa35094-d
new file mode 100644
index 0000000..e7916ae
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/69/69a8a35487589134e88fae6e9944960fe39e95e6e490fe2cb639ab48aaa35094-d
@@ -0,0 +1 @@
+./cart.go
diff --git a/.cell-installs/xdg-cache/go-build/69/69bc9d9aab36a9b1b2c576399106bcac4c158bc13563cff9e4dc550d8bca7927-d b/.cell-installs/xdg-cache/go-build/69/69bc9d9aab36a9b1b2c576399106bcac4c158bc13563cff9e4dc550d8bca7927-d
new file mode 100644
index 0000000..dbd4c68
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/69/69bc9d9aab36a9b1b2c576399106bcac4c158bc13563cff9e4dc550d8bca7927-d differ
diff --git a/.cell-installs/xdg-cache/go-build/69/69be00dd0a9ea45be83ab1a9eb79a92389af9a549378ae700202e18ce1459fc5-d b/.cell-installs/xdg-cache/go-build/69/69be00dd0a9ea45be83ab1a9eb79a92389af9a549378ae700202e18ce1459fc5-d
new file mode 100644
index 0000000..b48de3f
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/69/69be00dd0a9ea45be83ab1a9eb79a92389af9a549378ae700202e18ce1459fc5-d differ
diff --git a/.cell-installs/xdg-cache/go-build/6a/6a0878351653a7d7ac30e79ee7d663e70ecd5de0c8967be2af335d9095e49df4-d b/.cell-installs/xdg-cache/go-build/6a/6a0878351653a7d7ac30e79ee7d663e70ecd5de0c8967be2af335d9095e49df4-d
new file mode 100644
index 0000000..4a942ac
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/6a/6a0878351653a7d7ac30e79ee7d663e70ecd5de0c8967be2af335d9095e49df4-d differ
diff --git a/.cell-installs/xdg-cache/go-build/6a/6a0c5fcd36302f3907f7842cd08ebc67bdd8908b919d15ff4c84bb6b66eefc79-d b/.cell-installs/xdg-cache/go-build/6a/6a0c5fcd36302f3907f7842cd08ebc67bdd8908b919d15ff4c84bb6b66eefc79-d
new file mode 100644
index 0000000..92b6c98
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/6a/6a0c5fcd36302f3907f7842cd08ebc67bdd8908b919d15ff4c84bb6b66eefc79-d differ
diff --git a/.cell-installs/xdg-cache/go-build/6a/6a5f4ad03f4f7eba2af91c159af3c8b6b87b205d447b40da24cadd7b1a9fa486-a b/.cell-installs/xdg-cache/go-build/6a/6a5f4ad03f4f7eba2af91c159af3c8b6b87b205d447b40da24cadd7b1a9fa486-a
new file mode 100644
index 0000000..7b89194
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6a/6a5f4ad03f4f7eba2af91c159af3c8b6b87b205d447b40da24cadd7b1a9fa486-a
@@ -0,0 +1 @@
+v1 6a5f4ad03f4f7eba2af91c159af3c8b6b87b205d447b40da24cadd7b1a9fa486 2f5d15f24b43049cb604cfc138d3efd8948d0b2e25baee4123b02256b19a180e                24751  1787953153963016538
diff --git a/.cell-installs/xdg-cache/go-build/6a/6a685cdba70dc2973550dae7daea6e4618d8b2e846e525dc9efb5114a2fd03cb-d b/.cell-installs/xdg-cache/go-build/6a/6a685cdba70dc2973550dae7daea6e4618d8b2e846e525dc9efb5114a2fd03cb-d
new file mode 100644
index 0000000..ca28533
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/6a/6a685cdba70dc2973550dae7daea6e4618d8b2e846e525dc9efb5114a2fd03cb-d differ
diff --git a/.cell-installs/xdg-cache/go-build/6a/6a687976e88a1db5e810657299cd63c545d4edd317e0eaafe9d032d9c5d66a22-a b/.cell-installs/xdg-cache/go-build/6a/6a687976e88a1db5e810657299cd63c545d4edd317e0eaafe9d032d9c5d66a22-a
new file mode 100644
index 0000000..879fa51
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6a/6a687976e88a1db5e810657299cd63c545d4edd317e0eaafe9d032d9c5d66a22-a
@@ -0,0 +1 @@
+v1 6a687976e88a1db5e810657299cd63c545d4edd317e0eaafe9d032d9c5d66a22 2523a88aa3aa51c9638a26fe61b0ba0e6021d71066fc40d0c77bafcb88003e6e                 8324  1787953567795464653
diff --git a/.cell-installs/xdg-cache/go-build/6a/6aa8517b4b8a32b3d05114025cf57a94ac10dfafad726248bb9912753e2671d0-a b/.cell-installs/xdg-cache/go-build/6a/6aa8517b4b8a32b3d05114025cf57a94ac10dfafad726248bb9912753e2671d0-a
new file mode 100644
index 0000000..cd48a14
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6a/6aa8517b4b8a32b3d05114025cf57a94ac10dfafad726248bb9912753e2671d0-a
@@ -0,0 +1 @@
+v1 6aa8517b4b8a32b3d05114025cf57a94ac10dfafad726248bb9912753e2671d0 a784140605c1f2fa0d84e32bba5b4d1baeded52b1898e94766f8793b818fc995                 1667  1787953170145494532
diff --git a/.cell-installs/xdg-cache/go-build/6a/6ac684b779dad008b4e8f57411749f7dfce5990a32b22f71db1c290070d0c1b5-d b/.cell-installs/xdg-cache/go-build/6a/6ac684b779dad008b4e8f57411749f7dfce5990a32b22f71db1c290070d0c1b5-d
new file mode 100644
index 0000000..f932643
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/6a/6ac684b779dad008b4e8f57411749f7dfce5990a32b22f71db1c290070d0c1b5-d differ
diff --git a/.cell-installs/xdg-cache/go-build/6a/6af88457a00ec61fce8dd11428da5febd90bc90fe146fa8db42f9ba6e0b09226-d b/.cell-installs/xdg-cache/go-build/6a/6af88457a00ec61fce8dd11428da5febd90bc90fe146fa8db42f9ba6e0b09226-d
new file mode 100644
index 0000000..4c4d658
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/6a/6af88457a00ec61fce8dd11428da5febd90bc90fe146fa8db42f9ba6e0b09226-d differ
diff --git a/.cell-installs/xdg-cache/go-build/6b/6b2eefefcb70d13650b2d2ce51924b6be403530019bb4104634dfffe4d49d711-a b/.cell-installs/xdg-cache/go-build/6b/6b2eefefcb70d13650b2d2ce51924b6be403530019bb4104634dfffe4d49d711-a
new file mode 100644
index 0000000..bc78394
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6b/6b2eefefcb70d13650b2d2ce51924b6be403530019bb4104634dfffe4d49d711-a
@@ -0,0 +1 @@
+v1 6b2eefefcb70d13650b2d2ce51924b6be403530019bb4104634dfffe4d49d711 22e5f9cc95da6a3a4c76163406e0abc474b1cf29ecfb5d64189541959ad80fdb                  796  1787953771531186284
diff --git a/.cell-installs/xdg-cache/go-build/6b/6bbe7502fb11d745b15f0c4d587b99c369be0f582846a5bf243f686779b0ff75-a b/.cell-installs/xdg-cache/go-build/6b/6bbe7502fb11d745b15f0c4d587b99c369be0f582846a5bf243f686779b0ff75-a
new file mode 100644
index 0000000..d31f901
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6b/6bbe7502fb11d745b15f0c4d587b99c369be0f582846a5bf243f686779b0ff75-a
@@ -0,0 +1 @@
+v1 6bbe7502fb11d745b15f0c4d587b99c369be0f582846a5bf243f686779b0ff75 b130d991c9796b6be26975c2d639b849a906a53a2217f96f3a00fb6aa5e7da24                 1475  1787953170145190884
diff --git a/.cell-installs/xdg-cache/go-build/6c/6c351968fbbed5e44395ec0ea3bb66f3a9e546ccc6d8dc8067be71e17dfd2c66-a b/.cell-installs/xdg-cache/go-build/6c/6c351968fbbed5e44395ec0ea3bb66f3a9e546ccc6d8dc8067be71e17dfd2c66-a
new file mode 100644
index 0000000..67f90f8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6c/6c351968fbbed5e44395ec0ea3bb66f3a9e546ccc6d8dc8067be71e17dfd2c66-a
@@ -0,0 +1 @@
+v1 6c351968fbbed5e44395ec0ea3bb66f3a9e546ccc6d8dc8067be71e17dfd2c66 077c4c84129ee8b3bb95bdcaecd24bff550d8c7ecae971d146bf9590de7b41a9                   12  1787953569911125787
diff --git a/.cell-installs/xdg-cache/go-build/6c/6c93a68c1c741d6969027a84e8e30bdc9918d8ed6637e340b826397304bd0658-a b/.cell-installs/xdg-cache/go-build/6c/6c93a68c1c741d6969027a84e8e30bdc9918d8ed6637e340b826397304bd0658-a
new file mode 100644
index 0000000..e516874
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6c/6c93a68c1c741d6969027a84e8e30bdc9918d8ed6637e340b826397304bd0658-a
@@ -0,0 +1 @@
+v1 6c93a68c1c741d6969027a84e8e30bdc9918d8ed6637e340b826397304bd0658 7543165f27ee306c7643b83ecc794a4fb213a39b0652ae085a14da0b1ead0851                  919  1787953170145029130
diff --git a/.cell-installs/xdg-cache/go-build/6c/6ca02d3d1b924e9042376a95c77b637f5eddc77cdde0ffc9e006566baf2d9705-a b/.cell-installs/xdg-cache/go-build/6c/6ca02d3d1b924e9042376a95c77b637f5eddc77cdde0ffc9e006566baf2d9705-a
new file mode 100644
index 0000000..6434af3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6c/6ca02d3d1b924e9042376a95c77b637f5eddc77cdde0ffc9e006566baf2d9705-a
@@ -0,0 +1 @@
+v1 6ca02d3d1b924e9042376a95c77b637f5eddc77cdde0ffc9e006566baf2d9705 2c6eee214353b1e2363eb8b0b2fc3d18a009327898c7399f677cdf0af6df029b                  962  1787953569728027343
diff --git a/.cell-installs/xdg-cache/go-build/6c/6cadbb8cb6471c63290462f1746257837f65958ee5703730c67e9f0db3a56951-a b/.cell-installs/xdg-cache/go-build/6c/6cadbb8cb6471c63290462f1746257837f65958ee5703730c67e9f0db3a56951-a
new file mode 100644
index 0000000..4cecc97
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6c/6cadbb8cb6471c63290462f1746257837f65958ee5703730c67e9f0db3a56951-a
@@ -0,0 +1 @@
+v1 6cadbb8cb6471c63290462f1746257837f65958ee5703730c67e9f0db3a56951 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569629150574
diff --git a/.cell-installs/xdg-cache/go-build/6c/6cb56b714a2f2243fe20536d7bb27bf123d9b380fa06f3bc867a01b09dfe43d3-d b/.cell-installs/xdg-cache/go-build/6c/6cb56b714a2f2243fe20536d7bb27bf123d9b380fa06f3bc867a01b09dfe43d3-d
new file mode 100644
index 0000000..ef7212e
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/6c/6cb56b714a2f2243fe20536d7bb27bf123d9b380fa06f3bc867a01b09dfe43d3-d differ
diff --git a/.cell-installs/xdg-cache/go-build/6c/6cdd4241dc286da77c5143ffd44842f54fca37f86c5d522de0de93b06d1e26f0-d b/.cell-installs/xdg-cache/go-build/6c/6cdd4241dc286da77c5143ffd44842f54fca37f86c5d522de0de93b06d1e26f0-d
new file mode 100644
index 0000000..1fa17c1
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/6c/6cdd4241dc286da77c5143ffd44842f54fca37f86c5d522de0de93b06d1e26f0-d differ
diff --git a/.cell-installs/xdg-cache/go-build/6c/6cf1e0a584f621921ee04b11c3d33d9cff776b86cb66cc75f477e857a4e08382-a b/.cell-installs/xdg-cache/go-build/6c/6cf1e0a584f621921ee04b11c3d33d9cff776b86cb66cc75f477e857a4e08382-a
new file mode 100644
index 0000000..f3fa679
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6c/6cf1e0a584f621921ee04b11c3d33d9cff776b86cb66cc75f477e857a4e08382-a
@@ -0,0 +1 @@
+v1 6cf1e0a584f621921ee04b11c3d33d9cff776b86cb66cc75f477e857a4e08382 d12ad4c5dafeffd94eace65d3cfad8ae8ce2f13b8dc59c9ed8be5e00522d6d5d                 2576  1787953170165252475
diff --git a/.cell-installs/xdg-cache/go-build/6c/6cfe37d61384882d5b4f99104ab47d1ef9817e1691432b57655d97ab0a2f80de-a b/.cell-installs/xdg-cache/go-build/6c/6cfe37d61384882d5b4f99104ab47d1ef9817e1691432b57655d97ab0a2f80de-a
new file mode 100644
index 0000000..cbb75f0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6c/6cfe37d61384882d5b4f99104ab47d1ef9817e1691432b57655d97ab0a2f80de-a
@@ -0,0 +1 @@
+v1 6cfe37d61384882d5b4f99104ab47d1ef9817e1691432b57655d97ab0a2f80de 37d4c7c3dfbee05fc71faad3db98f5a015a8516b3cd042850c0d9e8bfdda3d33                  457  1787953170181009163
diff --git a/.cell-installs/xdg-cache/go-build/6d/6d4682df2feb881f0f88308949ef264fd934db774324176b9fc38bd940f0b5ce-d b/.cell-installs/xdg-cache/go-build/6d/6d4682df2feb881f0f88308949ef264fd934db774324176b9fc38bd940f0b5ce-d
new file mode 100644
index 0000000..3e0bafd
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/6d/6d4682df2feb881f0f88308949ef264fd934db774324176b9fc38bd940f0b5ce-d differ
diff --git a/.cell-installs/xdg-cache/go-build/6d/6d590bbf5ddefea78601ded65d76a218744b652109e3a6ace9322190ff14906b-a b/.cell-installs/xdg-cache/go-build/6d/6d590bbf5ddefea78601ded65d76a218744b652109e3a6ace9322190ff14906b-a
new file mode 100644
index 0000000..63552ef
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6d/6d590bbf5ddefea78601ded65d76a218744b652109e3a6ace9322190ff14906b-a
@@ -0,0 +1 @@
+v1 6d590bbf5ddefea78601ded65d76a218744b652109e3a6ace9322190ff14906b 42814d21689788be40ab3428620dab2ba6d9a976b6fa72935536d3ec43fb0280                 1431  1787953170191933820
diff --git a/.cell-installs/xdg-cache/go-build/6d/6ddc10c551a135f9730719e8ee3c67c7006683da7031fc269e48021d1b6c1b4e-a b/.cell-installs/xdg-cache/go-build/6d/6ddc10c551a135f9730719e8ee3c67c7006683da7031fc269e48021d1b6c1b4e-a
new file mode 100644
index 0000000..c89eb90
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6d/6ddc10c551a135f9730719e8ee3c67c7006683da7031fc269e48021d1b6c1b4e-a
@@ -0,0 +1 @@
+v1 6ddc10c551a135f9730719e8ee3c67c7006683da7031fc269e48021d1b6c1b4e e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569485620724
diff --git a/.cell-installs/xdg-cache/go-build/6e/6e6ba44be07aeb1c53a42c81fc8b810584d3a84db038c613baec97231dd693bd-a b/.cell-installs/xdg-cache/go-build/6e/6e6ba44be07aeb1c53a42c81fc8b810584d3a84db038c613baec97231dd693bd-a
new file mode 100644
index 0000000..3b83e5d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6e/6e6ba44be07aeb1c53a42c81fc8b810584d3a84db038c613baec97231dd693bd-a
@@ -0,0 +1 @@
+v1 6e6ba44be07aeb1c53a42c81fc8b810584d3a84db038c613baec97231dd693bd 1cdb08f62987cb4e32e1b27035f18b6376b2570b872edf0fa1bcdfc14f439293                  401  1787953153949849039
diff --git a/.cell-installs/xdg-cache/go-build/6e/6ec904ca58b4a275b4211e63621adcf1ec2045c48fadb479332840dfb53ca2c5-d b/.cell-installs/xdg-cache/go-build/6e/6ec904ca58b4a275b4211e63621adcf1ec2045c48fadb479332840dfb53ca2c5-d
new file mode 100644
index 0000000..9047752
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/6e/6ec904ca58b4a275b4211e63621adcf1ec2045c48fadb479332840dfb53ca2c5-d differ
diff --git a/.cell-installs/xdg-cache/go-build/6e/6ecf6f7732403d515f4956a24dfe6b75b7dfe31d12a7cc3798e875e7be3cf382-d b/.cell-installs/xdg-cache/go-build/6e/6ecf6f7732403d515f4956a24dfe6b75b7dfe31d12a7cc3798e875e7be3cf382-d
new file mode 100644
index 0000000..7f6704d
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/6e/6ecf6f7732403d515f4956a24dfe6b75b7dfe31d12a7cc3798e875e7be3cf382-d differ
diff --git a/.cell-installs/xdg-cache/go-build/6e/6ee1402f0df2a8d8d9c0bcea60f5f0b496fac6b010e52479301c1bb3a6b57f10-a b/.cell-installs/xdg-cache/go-build/6e/6ee1402f0df2a8d8d9c0bcea60f5f0b496fac6b010e52479301c1bb3a6b57f10-a
new file mode 100644
index 0000000..7ea8477
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6e/6ee1402f0df2a8d8d9c0bcea60f5f0b496fac6b010e52479301c1bb3a6b57f10-a
@@ -0,0 +1 @@
+v1 6ee1402f0df2a8d8d9c0bcea60f5f0b496fac6b010e52479301c1bb3a6b57f10 66b8f8f96de7a4b0b06c792689baf964d121a116dba01dd3a7b7ebdd2132cd01                  510  1787953153963955024
diff --git a/.cell-installs/xdg-cache/go-build/6f/6f0d7cd7a0e2e4dc50752b89c23b048fc0d67cb571276b0554cce28a65e064d2-d b/.cell-installs/xdg-cache/go-build/6f/6f0d7cd7a0e2e4dc50752b89c23b048fc0d67cb571276b0554cce28a65e064d2-d
new file mode 100644
index 0000000..8824e56
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6f/6f0d7cd7a0e2e4dc50752b89c23b048fc0d67cb571276b0554cce28a65e064d2-d
@@ -0,0 +1,6 @@
+./consts.go
+./consts_norace.go
+./intrinsics.go
+./nih.go
+./sys.go
+./zversion.go
diff --git a/.cell-installs/xdg-cache/go-build/6f/6f45513c26089e0787a30c9525bc03716b18622a2c2b5b77152631b33606c45c-d b/.cell-installs/xdg-cache/go-build/6f/6f45513c26089e0787a30c9525bc03716b18622a2c2b5b77152631b33606c45c-d
new file mode 100644
index 0000000..b1b6209
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/6f/6f45513c26089e0787a30c9525bc03716b18622a2c2b5b77152631b33606c45c-d differ
diff --git a/.cell-installs/xdg-cache/go-build/6f/6f5661a563ec570d829ab5f0a418c5c435505f8f4f5b4d3ec54a6a96b51c3f2c-d b/.cell-installs/xdg-cache/go-build/6f/6f5661a563ec570d829ab5f0a418c5c435505f8f4f5b4d3ec54a6a96b51c3f2c-d
new file mode 100644
index 0000000..8bdaca8
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/6f/6f5661a563ec570d829ab5f0a418c5c435505f8f4f5b4d3ec54a6a96b51c3f2c-d differ
diff --git a/.cell-installs/xdg-cache/go-build/6f/6f6ca331ba2a812c6932abd7048299a2e2122b9470a2ddac531ee9461ef2677f-a b/.cell-installs/xdg-cache/go-build/6f/6f6ca331ba2a812c6932abd7048299a2e2122b9470a2ddac531ee9461ef2677f-a
new file mode 100644
index 0000000..4cc9c3f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6f/6f6ca331ba2a812c6932abd7048299a2e2122b9470a2ddac531ee9461ef2677f-a
@@ -0,0 +1 @@
+v1 6f6ca331ba2a812c6932abd7048299a2e2122b9470a2ddac531ee9461ef2677f 4851cd1a6a2902eec82a2d44a74b7c9a22b858e41b55299c47291bf076d59c14                   56  1787954418337996908
diff --git a/.cell-installs/xdg-cache/go-build/6f/6f8097cec165d96cc29a8c1173e8b460caf7e64e729e4051e140c0ad3753edb1-a b/.cell-installs/xdg-cache/go-build/6f/6f8097cec165d96cc29a8c1173e8b460caf7e64e729e4051e140c0ad3753edb1-a
new file mode 100644
index 0000000..53db34b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6f/6f8097cec165d96cc29a8c1173e8b460caf7e64e729e4051e140c0ad3753edb1-a
@@ -0,0 +1 @@
+v1 6f8097cec165d96cc29a8c1173e8b460caf7e64e729e4051e140c0ad3753edb1 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570255461785
diff --git a/.cell-installs/xdg-cache/go-build/6f/6f9eb4c74e8f7c282f5d72f1eddccee17e5a424267df706d95338f763a31af4f-a b/.cell-installs/xdg-cache/go-build/6f/6f9eb4c74e8f7c282f5d72f1eddccee17e5a424267df706d95338f763a31af4f-a
new file mode 100644
index 0000000..55f4607
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6f/6f9eb4c74e8f7c282f5d72f1eddccee17e5a424267df706d95338f763a31af4f-a
@@ -0,0 +1 @@
+v1 6f9eb4c74e8f7c282f5d72f1eddccee17e5a424267df706d95338f763a31af4f f0ee9d7b8fbb0afac809cb6c46cee7fd3a68befdf643ccdd00533820a8926177                   10  1787953567790090322
diff --git a/.cell-installs/xdg-cache/go-build/6f/6fc9cacac9cf2c42030d4cf215835cedeb4d5a3d3537da52426385e1a4cf26ae-a b/.cell-installs/xdg-cache/go-build/6f/6fc9cacac9cf2c42030d4cf215835cedeb4d5a3d3537da52426385e1a4cf26ae-a
new file mode 100644
index 0000000..1d1ebee
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6f/6fc9cacac9cf2c42030d4cf215835cedeb4d5a3d3537da52426385e1a4cf26ae-a
@@ -0,0 +1 @@
+v1 6fc9cacac9cf2c42030d4cf215835cedeb4d5a3d3537da52426385e1a4cf26ae e938a758c5f73fd4cc18f356a0551b65fb020bb5b71b0eebe654e2f9f4160d39               375150  1787953568854464526
diff --git a/.cell-installs/xdg-cache/go-build/6f/6fdc5280311869b3058d5977f4fb729a80ff43f24629a98a5684ced7f4edc50c-a b/.cell-installs/xdg-cache/go-build/6f/6fdc5280311869b3058d5977f4fb729a80ff43f24629a98a5684ced7f4edc50c-a
new file mode 100644
index 0000000..bc0ce3c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/6f/6fdc5280311869b3058d5977f4fb729a80ff43f24629a98a5684ced7f4edc50c-a
@@ -0,0 +1 @@
+v1 6fdc5280311869b3058d5977f4fb729a80ff43f24629a98a5684ced7f4edc50c 69a8a35487589134e88fae6e9944960fe39e95e6e490fe2cb639ab48aaa35094                   10  1787953775794833897
diff --git a/.cell-installs/xdg-cache/go-build/70/7009ac55ae3028330bd96c098a988267a3b01cd618bd6f459ace6218624a79c2-d b/.cell-installs/xdg-cache/go-build/70/7009ac55ae3028330bd96c098a988267a3b01cd618bd6f459ace6218624a79c2-d
new file mode 100644
index 0000000..7171444
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/70/7009ac55ae3028330bd96c098a988267a3b01cd618bd6f459ace6218624a79c2-d differ
diff --git a/.cell-installs/xdg-cache/go-build/70/70402071cfb27d1a2a4b79dd54dca59f811bf4f410636f06e2be349fddea172b-d b/.cell-installs/xdg-cache/go-build/70/70402071cfb27d1a2a4b79dd54dca59f811bf4f410636f06e2be349fddea172b-d
new file mode 100644
index 0000000..8132c63
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/70/70402071cfb27d1a2a4b79dd54dca59f811bf4f410636f06e2be349fddea172b-d differ
diff --git a/.cell-installs/xdg-cache/go-build/70/704cd4b6348a76be744fa2e9d4f017a48bfc0111fe9bf62fba2f23b1ab5566ed-d b/.cell-installs/xdg-cache/go-build/70/704cd4b6348a76be744fa2e9d4f017a48bfc0111fe9bf62fba2f23b1ab5566ed-d
new file mode 100644
index 0000000..da38da1
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/70/704cd4b6348a76be744fa2e9d4f017a48bfc0111fe9bf62fba2f23b1ab5566ed-d
@@ -0,0 +1,7 @@
+./atomic_amd64.go
+./doc.go
+./stubs.go
+./types.go
+./types_64bit.go
+./unaligned.go
+./atomic_amd64.s
diff --git a/.cell-installs/xdg-cache/go-build/70/707b5ff4798b9429dc3439893e0632908275192e1df6b19946db10adcd9cc453-a b/.cell-installs/xdg-cache/go-build/70/707b5ff4798b9429dc3439893e0632908275192e1df6b19946db10adcd9cc453-a
new file mode 100644
index 0000000..61b8115
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/70/707b5ff4798b9429dc3439893e0632908275192e1df6b19946db10adcd9cc453-a
@@ -0,0 +1 @@
+v1 707b5ff4798b9429dc3439893e0632908275192e1df6b19946db10adcd9cc453 58353caac093da847b29d3aa534bb8cbb4ba13d3cec4b88010cb171852493bc1               514030  1787953568888441975
diff --git a/.cell-installs/xdg-cache/go-build/71/710559d46f53e97d75a5427b0a28b0526ca3e8c7c7ba96839cf91399d61169b7-d b/.cell-installs/xdg-cache/go-build/71/710559d46f53e97d75a5427b0a28b0526ca3e8c7c7ba96839cf91399d61169b7-d
new file mode 100644
index 0000000..4e84eb8
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/71/710559d46f53e97d75a5427b0a28b0526ca3e8c7c7ba96839cf91399d61169b7-d differ
diff --git a/.cell-installs/xdg-cache/go-build/71/7108bc836ff13c376ecf070ba50c1bfafd3e90a39acb2397fe45d769973f09ac-d b/.cell-installs/xdg-cache/go-build/71/7108bc836ff13c376ecf070ba50c1bfafd3e90a39acb2397fe45d769973f09ac-d
new file mode 100644
index 0000000..f4c332a
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/71/7108bc836ff13c376ecf070ba50c1bfafd3e90a39acb2397fe45d769973f09ac-d differ
diff --git a/.cell-installs/xdg-cache/go-build/71/71663442f4be87697bed0ef6a6f5d62aee55e546791a73518a4575fa44250aa5-d b/.cell-installs/xdg-cache/go-build/71/71663442f4be87697bed0ef6a6f5d62aee55e546791a73518a4575fa44250aa5-d
new file mode 100644
index 0000000..177a23d
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/71/71663442f4be87697bed0ef6a6f5d62aee55e546791a73518a4575fa44250aa5-d differ
diff --git a/.cell-installs/xdg-cache/go-build/71/71a0b70b9a74d900d3b08b86c00642f172463dfc0acce3245ba79f24917b7695-a b/.cell-installs/xdg-cache/go-build/71/71a0b70b9a74d900d3b08b86c00642f172463dfc0acce3245ba79f24917b7695-a
new file mode 100644
index 0000000..8fa5d95
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/71/71a0b70b9a74d900d3b08b86c00642f172463dfc0acce3245ba79f24917b7695-a
@@ -0,0 +1 @@
+v1 71a0b70b9a74d900d3b08b86c00642f172463dfc0acce3245ba79f24917b7695 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570059519131
diff --git a/.cell-installs/xdg-cache/go-build/72/7268825a631adbbde072cfbf30e0e8fc35078e90f1a38c9d4e53c206e2039f41-d b/.cell-installs/xdg-cache/go-build/72/7268825a631adbbde072cfbf30e0e8fc35078e90f1a38c9d4e53c206e2039f41-d
new file mode 100644
index 0000000..4d4674e
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/72/7268825a631adbbde072cfbf30e0e8fc35078e90f1a38c9d4e53c206e2039f41-d
@@ -0,0 +1,2 @@
+./gunzip.go
+./gzip.go
diff --git a/.cell-installs/xdg-cache/go-build/72/72859f1b45db304cc7987d3478a9645a5cd767f44434bbc30bcb7f6aa39843dd-d b/.cell-installs/xdg-cache/go-build/72/72859f1b45db304cc7987d3478a9645a5cd767f44434bbc30bcb7f6aa39843dd-d
new file mode 100644
index 0000000..f1234c4
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/72/72859f1b45db304cc7987d3478a9645a5cd767f44434bbc30bcb7f6aa39843dd-d
@@ -0,0 +1,59 @@
+./abs.go
+./acosh.go
+./asin.go
+./asinh.go
+./atan.go
+./atan2.go
+./atanh.go
+./bits.go
+./cbrt.go
+./const.go
+./copysign.go
+./dim.go
+./dim_asm.go
+./erf.go
+./erfinv.go
+./exp.go
+./exp2_noasm.go
+./exp_amd64.go
+./exp_asm.go
+./expm1.go
+./floor.go
+./floor_asm.go
+./fma.go
+./frexp.go
+./gamma.go
+./hypot.go
+./hypot_asm.go
+./j0.go
+./j1.go
+./jn.go
+./ldexp.go
+./lgamma.go
+./log.go
+./log10.go
+./log1p.go
+./log_asm.go
+./logb.go
+./mod.go
+./modf.go
+./modf_noasm.go
+./nextafter.go
+./pow.go
+./pow10.go
+./remainder.go
+./signbit.go
+./sin.go
+./sincos.go
+./sinh.go
+./sqrt.go
+./stubs.go
+./tan.go
+./tanh.go
+./trig_reduce.go
+./unsafe.go
+./dim_amd64.s
+./exp_amd64.s
+./floor_amd64.s
+./hypot_amd64.s
+./log_amd64.s
diff --git a/.cell-installs/xdg-cache/go-build/72/72a694b10d3fab47955610ac3e01c060ce0ef96134e6f7d7bc2a3e6db03a56d8-a b/.cell-installs/xdg-cache/go-build/72/72a694b10d3fab47955610ac3e01c060ce0ef96134e6f7d7bc2a3e6db03a56d8-a
new file mode 100644
index 0000000..50101a2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/72/72a694b10d3fab47955610ac3e01c060ce0ef96134e6f7d7bc2a3e6db03a56d8-a
@@ -0,0 +1 @@
+v1 72a694b10d3fab47955610ac3e01c060ce0ef96134e6f7d7bc2a3e6db03a56d8 7009ac55ae3028330bd96c098a988267a3b01cd618bd6f459ace6218624a79c2               105784  1787953567797843171
diff --git a/.cell-installs/xdg-cache/go-build/72/72b4795a42b4564ec7d363df1ae227a886ce239a086e50032c3b03a44ec66dc6-a b/.cell-installs/xdg-cache/go-build/72/72b4795a42b4564ec7d363df1ae227a886ce239a086e50032c3b03a44ec66dc6-a
new file mode 100644
index 0000000..e5da022
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/72/72b4795a42b4564ec7d363df1ae227a886ce239a086e50032c3b03a44ec66dc6-a
@@ -0,0 +1 @@
+v1 72b4795a42b4564ec7d363df1ae227a886ce239a086e50032c3b03a44ec66dc6 54d3b01966fb7a0a04821fa99ad7db66a2b28976939b87a25da1b2b3ba5a50b6                  215  1787953569675145332
diff --git a/.cell-installs/xdg-cache/go-build/73/737802c136163f53e2d12c17d6fd5d4f03922763f552a2de21f4f2a62d73af2c-d b/.cell-installs/xdg-cache/go-build/73/737802c136163f53e2d12c17d6fd5d4f03922763f552a2de21f4f2a62d73af2c-d
new file mode 100644
index 0000000..e5b55b5
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/73/737802c136163f53e2d12c17d6fd5d4f03922763f552a2de21f4f2a62d73af2c-d
@@ -0,0 +1,3 @@
+./position.go
+./serialize.go
+./token.go
diff --git a/.cell-installs/xdg-cache/go-build/73/73da4db3a27e0f68902f139a590f8484b0a39682f98c26cb13b262f49474eeb8-d b/.cell-installs/xdg-cache/go-build/73/73da4db3a27e0f68902f139a590f8484b0a39682f98c26cb13b262f49474eeb8-d
new file mode 100644
index 0000000..2a974c9
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/73/73da4db3a27e0f68902f139a590f8484b0a39682f98c26cb13b262f49474eeb8-d
@@ -0,0 +1 @@
+./itoa.go
diff --git a/.cell-installs/xdg-cache/go-build/73/73e7e0c70a2a2e5a0fd82b8651902bcbf5e93081ba1a91ce573f5a0f0ea48e48-a b/.cell-installs/xdg-cache/go-build/73/73e7e0c70a2a2e5a0fd82b8651902bcbf5e93081ba1a91ce573f5a0f0ea48e48-a
new file mode 100644
index 0000000..7cf0e55
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/73/73e7e0c70a2a2e5a0fd82b8651902bcbf5e93081ba1a91ce573f5a0f0ea48e48-a
@@ -0,0 +1 @@
+v1 73e7e0c70a2a2e5a0fd82b8651902bcbf5e93081ba1a91ce573f5a0f0ea48e48 6ec904ca58b4a275b4211e63621adcf1ec2045c48fadb479332840dfb53ca2c5                 1203  1787953771566087818
diff --git a/.cell-installs/xdg-cache/go-build/73/73f2b33f2b6d717a3a3ab5da9e0976b86d5cd4f5da75d381f48f0634be8e1f69-a b/.cell-installs/xdg-cache/go-build/73/73f2b33f2b6d717a3a3ab5da9e0976b86d5cd4f5da75d381f48f0634be8e1f69-a
new file mode 100644
index 0000000..eb896ed
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/73/73f2b33f2b6d717a3a3ab5da9e0976b86d5cd4f5da75d381f48f0634be8e1f69-a
@@ -0,0 +1 @@
+v1 73f2b33f2b6d717a3a3ab5da9e0976b86d5cd4f5da75d381f48f0634be8e1f69 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569915268207
diff --git a/.cell-installs/xdg-cache/go-build/74/740b4e766dd63324ec14269ffb68e02e7bfc21f761f169ac433b17fce0a2a98f-a b/.cell-installs/xdg-cache/go-build/74/740b4e766dd63324ec14269ffb68e02e7bfc21f761f169ac433b17fce0a2a98f-a
new file mode 100644
index 0000000..5c86ad8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/74/740b4e766dd63324ec14269ffb68e02e7bfc21f761f169ac433b17fce0a2a98f-a
@@ -0,0 +1 @@
+v1 740b4e766dd63324ec14269ffb68e02e7bfc21f761f169ac433b17fce0a2a98f 3bfdde117bc14d60ad31a0c40bf88d9f597ee4f635b552089f69d10e3ff80099               110314  1787953569912678987
diff --git a/.cell-installs/xdg-cache/go-build/74/740c8793dd674a401bb9cc53cf825a0b5144c385397b7186cdd270b35bf2b8a3-a b/.cell-installs/xdg-cache/go-build/74/740c8793dd674a401bb9cc53cf825a0b5144c385397b7186cdd270b35bf2b8a3-a
new file mode 100644
index 0000000..ba94792
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/74/740c8793dd674a401bb9cc53cf825a0b5144c385397b7186cdd270b35bf2b8a3-a
@@ -0,0 +1 @@
+v1 740c8793dd674a401bb9cc53cf825a0b5144c385397b7186cdd270b35bf2b8a3 aaaf863ad8f66e3e28d7c4ad25a42da64cdd92a8874d387dc7feb48da8dc5bbe                 1744  1787953567719069065
diff --git a/.cell-installs/xdg-cache/go-build/74/74ce833c4445f2b838bfec996bb526864412a03230f322d035589e9d63b818d2-a b/.cell-installs/xdg-cache/go-build/74/74ce833c4445f2b838bfec996bb526864412a03230f322d035589e9d63b818d2-a
new file mode 100644
index 0000000..7a15d1c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/74/74ce833c4445f2b838bfec996bb526864412a03230f322d035589e9d63b818d2-a
@@ -0,0 +1 @@
+v1 74ce833c4445f2b838bfec996bb526864412a03230f322d035589e9d63b818d2 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567806976418
diff --git a/.cell-installs/xdg-cache/go-build/75/75010eb66a4a58ae07d55e9fd07acc4267e30ab83245e0d8a49a612a23bc6f05-a b/.cell-installs/xdg-cache/go-build/75/75010eb66a4a58ae07d55e9fd07acc4267e30ab83245e0d8a49a612a23bc6f05-a
new file mode 100644
index 0000000..98b5112
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/75/75010eb66a4a58ae07d55e9fd07acc4267e30ab83245e0d8a49a612a23bc6f05-a
@@ -0,0 +1 @@
+v1 75010eb66a4a58ae07d55e9fd07acc4267e30ab83245e0d8a49a612a23bc6f05 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569108747294
diff --git a/.cell-installs/xdg-cache/go-build/75/752e4045a6dfde6aae12ce3e0faf5685918ff08e80e4707d06b5cf3fb88b4089-d b/.cell-installs/xdg-cache/go-build/75/752e4045a6dfde6aae12ce3e0faf5685918ff08e80e4707d06b5cf3fb88b4089-d
new file mode 100644
index 0000000..58d2e9c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/75/752e4045a6dfde6aae12ce3e0faf5685918ff08e80e4707d06b5cf3fb88b4089-d differ
diff --git a/.cell-installs/xdg-cache/go-build/75/7543165f27ee306c7643b83ecc794a4fb213a39b0652ae085a14da0b1ead0851-d b/.cell-installs/xdg-cache/go-build/75/7543165f27ee306c7643b83ecc794a4fb213a39b0652ae085a14da0b1ead0851-d
new file mode 100644
index 0000000..04ca876
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/75/7543165f27ee306c7643b83ecc794a4fb213a39b0652ae085a14da0b1ead0851-d differ
diff --git a/.cell-installs/xdg-cache/go-build/75/757f74246589be00936e8e4a2aed1ebf2e009bab86f0cfa6bd9d59cba84a100e-a b/.cell-installs/xdg-cache/go-build/75/757f74246589be00936e8e4a2aed1ebf2e009bab86f0cfa6bd9d59cba84a100e-a
new file mode 100644
index 0000000..c378e95
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/75/757f74246589be00936e8e4a2aed1ebf2e009bab86f0cfa6bd9d59cba84a100e-a
@@ -0,0 +1 @@
+v1 757f74246589be00936e8e4a2aed1ebf2e009bab86f0cfa6bd9d59cba84a100e adb61f4f74d6f24f55c2da511b539047725cf5515ad6aa5f012ee57271ddc352                13876  1787953567787033089
diff --git a/.cell-installs/xdg-cache/go-build/75/7591f851b43bff8849ef351a7585c04e0e124749f86170c7ae6ac1a3c50aa7d7-a b/.cell-installs/xdg-cache/go-build/75/7591f851b43bff8849ef351a7585c04e0e124749f86170c7ae6ac1a3c50aa7d7-a
new file mode 100644
index 0000000..a83dc76
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/75/7591f851b43bff8849ef351a7585c04e0e124749f86170c7ae6ac1a3c50aa7d7-a
@@ -0,0 +1 @@
+v1 7591f851b43bff8849ef351a7585c04e0e124749f86170c7ae6ac1a3c50aa7d7 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567806085763
diff --git a/.cell-installs/xdg-cache/go-build/75/759e113a2422a91e8358dddd3e4c1e72bdac49efd663a9abf543a977a707c567-a b/.cell-installs/xdg-cache/go-build/75/759e113a2422a91e8358dddd3e4c1e72bdac49efd663a9abf543a977a707c567-a
new file mode 100644
index 0000000..27cab35
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/75/759e113a2422a91e8358dddd3e4c1e72bdac49efd663a9abf543a977a707c567-a
@@ -0,0 +1 @@
+v1 759e113a2422a91e8358dddd3e4c1e72bdac49efd663a9abf543a977a707c567 9eb6294bc39979787b03eb7d39d5bf0cb5ae98f773ebcc790710c1d3e9773032                   25  1787953569916798322
diff --git a/.cell-installs/xdg-cache/go-build/75/75fb062c6c65fa531e2c3b3ce299c0ee5450b80e08f9e9fceaa825171d21ec5e-d b/.cell-installs/xdg-cache/go-build/75/75fb062c6c65fa531e2c3b3ce299c0ee5450b80e08f9e9fceaa825171d21ec5e-d
new file mode 100644
index 0000000..33cd8f7
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/75/75fb062c6c65fa531e2c3b3ce299c0ee5450b80e08f9e9fceaa825171d21ec5e-d differ
diff --git a/.cell-installs/xdg-cache/go-build/76/76029186b323a2ca18d7ce86edc395798cc665e3af3342c74c1df245352c6947-a b/.cell-installs/xdg-cache/go-build/76/76029186b323a2ca18d7ce86edc395798cc665e3af3342c74c1df245352c6947-a
new file mode 100644
index 0000000..47ec144
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/76/76029186b323a2ca18d7ce86edc395798cc665e3af3342c74c1df245352c6947-a
@@ -0,0 +1 @@
+v1 76029186b323a2ca18d7ce86edc395798cc665e3af3342c74c1df245352c6947 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568987159228
diff --git a/.cell-installs/xdg-cache/go-build/76/762010b63cb1fb7ed54fbf892e7764e268b9b3bc342592464abcbc8bd740b718-a b/.cell-installs/xdg-cache/go-build/76/762010b63cb1fb7ed54fbf892e7764e268b9b3bc342592464abcbc8bd740b718-a
new file mode 100644
index 0000000..cb9b665
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/76/762010b63cb1fb7ed54fbf892e7764e268b9b3bc342592464abcbc8bd740b718-a
@@ -0,0 +1 @@
+v1 762010b63cb1fb7ed54fbf892e7764e268b9b3bc342592464abcbc8bd740b718 8318c3a6d28c34f2da8a316ff95558632b51ed3cccfd1d21c202a4301e0354ea               172244  1787953570297149704
diff --git a/.cell-installs/xdg-cache/go-build/76/767e14dac5e9e561d4cb1244667bba86e800b6e3ae221609b41c3604f0baf2f9-a b/.cell-installs/xdg-cache/go-build/76/767e14dac5e9e561d4cb1244667bba86e800b6e3ae221609b41c3604f0baf2f9-a
new file mode 100644
index 0000000..e6dbfd4
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/76/767e14dac5e9e561d4cb1244667bba86e800b6e3ae221609b41c3604f0baf2f9-a
@@ -0,0 +1 @@
+v1 767e14dac5e9e561d4cb1244667bba86e800b6e3ae221609b41c3604f0baf2f9 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570315241145
diff --git a/.cell-installs/xdg-cache/go-build/76/76a190657ccd0db4615b611531fbb450d13fbb39c0fbe2bc7fbedf902686667d-d b/.cell-installs/xdg-cache/go-build/76/76a190657ccd0db4615b611531fbb450d13fbb39c0fbe2bc7fbedf902686667d-d
new file mode 100644
index 0000000..6812af1
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/76/76a190657ccd0db4615b611531fbb450d13fbb39c0fbe2bc7fbedf902686667d-d
@@ -0,0 +1 @@
+./flag.go
diff --git a/.cell-installs/xdg-cache/go-build/76/76a2843ffe08468309bd052e33f9040c405457c7907e4669116e91cb1c34937c-a b/.cell-installs/xdg-cache/go-build/76/76a2843ffe08468309bd052e33f9040c405457c7907e4669116e91cb1c34937c-a
new file mode 100644
index 0000000..f73d444
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/76/76a2843ffe08468309bd052e33f9040c405457c7907e4669116e91cb1c34937c-a
@@ -0,0 +1 @@
+v1 76a2843ffe08468309bd052e33f9040c405457c7907e4669116e91cb1c34937c ab7a7c43f2af3bf8f2152af5fce03bec5a7a430d744842dc3ea95636763a6fcd                10326  1787953170173811588
diff --git a/.cell-installs/xdg-cache/go-build/76/76c0b6d6cc48ec2b85e2fe619c78fa66f645f5938c468b73e4755c1a210a7f63-a b/.cell-installs/xdg-cache/go-build/76/76c0b6d6cc48ec2b85e2fe619c78fa66f645f5938c468b73e4755c1a210a7f63-a
new file mode 100644
index 0000000..0b4c8cf
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/76/76c0b6d6cc48ec2b85e2fe619c78fa66f645f5938c468b73e4755c1a210a7f63-a
@@ -0,0 +1 @@
+v1 76c0b6d6cc48ec2b85e2fe619c78fa66f645f5938c468b73e4755c1a210a7f63 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569328200418
diff --git a/.cell-installs/xdg-cache/go-build/76/76cbb554d5e9be4566f51998552c9ec85826ee78dc2277b742715c8227615fff-d b/.cell-installs/xdg-cache/go-build/76/76cbb554d5e9be4566f51998552c9ec85826ee78dc2277b742715c8227615fff-d
new file mode 100644
index 0000000..ba65640
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/76/76cbb554d5e9be4566f51998552c9ec85826ee78dc2277b742715c8227615fff-d differ
diff --git a/.cell-installs/xdg-cache/go-build/77/7762a79673dbbd45dad04f10e5370bac6dae2f7448684bd1b7f8df8f8f4bef9a-a b/.cell-installs/xdg-cache/go-build/77/7762a79673dbbd45dad04f10e5370bac6dae2f7448684bd1b7f8df8f8f4bef9a-a
new file mode 100644
index 0000000..c37c836
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/77/7762a79673dbbd45dad04f10e5370bac6dae2f7448684bd1b7f8df8f8f4bef9a-a
@@ -0,0 +1 @@
+v1 7762a79673dbbd45dad04f10e5370bac6dae2f7448684bd1b7f8df8f8f4bef9a 0db54e86c270078bcaff4c9ed5b78148461ba555d1b2b7835cdfc6e41691cd1a               136418  1787953570014400723
diff --git a/.cell-installs/xdg-cache/go-build/77/7768654d273ee88d6c3aae6047eb0d8155bc7d9f20aa64078c29969562346a6a-a b/.cell-installs/xdg-cache/go-build/77/7768654d273ee88d6c3aae6047eb0d8155bc7d9f20aa64078c29969562346a6a-a
new file mode 100644
index 0000000..3badafb
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/77/7768654d273ee88d6c3aae6047eb0d8155bc7d9f20aa64078c29969562346a6a-a
@@ -0,0 +1 @@
+v1 7768654d273ee88d6c3aae6047eb0d8155bc7d9f20aa64078c29969562346a6a e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569316134000
diff --git a/.cell-installs/xdg-cache/go-build/77/77c974c0d2d56cf26cd4ef503b306ebc90b5cdd4a6569cd9166a36517f102941-d b/.cell-installs/xdg-cache/go-build/77/77c974c0d2d56cf26cd4ef503b306ebc90b5cdd4a6569cd9166a36517f102941-d
new file mode 100644
index 0000000..3d36e7c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/77/77c974c0d2d56cf26cd4ef503b306ebc90b5cdd4a6569cd9166a36517f102941-d differ
diff --git a/.cell-installs/xdg-cache/go-build/78/7806adfa2dc06495469105f0f0d2d573cf1c3a7b2200244de504b4e506e3d726-a b/.cell-installs/xdg-cache/go-build/78/7806adfa2dc06495469105f0f0d2d573cf1c3a7b2200244de504b4e506e3d726-a
new file mode 100644
index 0000000..7bbef6f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/78/7806adfa2dc06495469105f0f0d2d573cf1c3a7b2200244de504b4e506e3d726-a
@@ -0,0 +1 @@
+v1 7806adfa2dc06495469105f0f0d2d573cf1c3a7b2200244de504b4e506e3d726 4757b6edef36d068d59d363e1eaebed83f9834f586468afec7f4e510f8953752                   61  1787953567785180922
diff --git a/.cell-installs/xdg-cache/go-build/78/783e45fcc5ab198c4af161606ff4c605132ccb09d92a04bf7cbc818d15ce8c37-a b/.cell-installs/xdg-cache/go-build/78/783e45fcc5ab198c4af161606ff4c605132ccb09d92a04bf7cbc818d15ce8c37-a
new file mode 100644
index 0000000..d3eef5b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/78/783e45fcc5ab198c4af161606ff4c605132ccb09d92a04bf7cbc818d15ce8c37-a
@@ -0,0 +1 @@
+v1 783e45fcc5ab198c4af161606ff4c605132ccb09d92a04bf7cbc818d15ce8c37 d062a0af5987ea4eb6b837c877b2d32de92b2b2c52fda7e41ff8f58ec66ee8fb                61848  1787953569923957535
diff --git a/.cell-installs/xdg-cache/go-build/78/784eaac5aaaa957c225112b1d4d4d6d14a68504875221afa4557fad96c0328df-a b/.cell-installs/xdg-cache/go-build/78/784eaac5aaaa957c225112b1d4d4d6d14a68504875221afa4557fad96c0328df-a
new file mode 100644
index 0000000..352e255
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/78/784eaac5aaaa957c225112b1d4d4d6d14a68504875221afa4557fad96c0328df-a
@@ -0,0 +1 @@
+v1 784eaac5aaaa957c225112b1d4d4d6d14a68504875221afa4557fad96c0328df e2c91c04bba4484d729b8ad853031cfae82ac16810de67ff674c9bd13fda8408                 1946  1787953153949904300
diff --git a/.cell-installs/xdg-cache/go-build/78/785a0612c34d0f9e3a167cb8914d93f947736afa69adf102aa09b071b081ff46-a b/.cell-installs/xdg-cache/go-build/78/785a0612c34d0f9e3a167cb8914d93f947736afa69adf102aa09b071b081ff46-a
new file mode 100644
index 0000000..95d5283
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/78/785a0612c34d0f9e3a167cb8914d93f947736afa69adf102aa09b071b081ff46-a
@@ -0,0 +1 @@
+v1 785a0612c34d0f9e3a167cb8914d93f947736afa69adf102aa09b071b081ff46 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570238977839
diff --git a/.cell-installs/xdg-cache/go-build/78/78b6056d76d1b6e5b30a66a7802628bb484a80df3ffc5673496283b9cc8565b3-a b/.cell-installs/xdg-cache/go-build/78/78b6056d76d1b6e5b30a66a7802628bb484a80df3ffc5673496283b9cc8565b3-a
new file mode 100644
index 0000000..4dad56b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/78/78b6056d76d1b6e5b30a66a7802628bb484a80df3ffc5673496283b9cc8565b3-a
@@ -0,0 +1 @@
+v1 78b6056d76d1b6e5b30a66a7802628bb484a80df3ffc5673496283b9cc8565b3 6f5661a563ec570d829ab5f0a418c5c435505f8f4f5b4d3ec54a6a96b51c3f2c                10547  1787953153973195727
diff --git a/.cell-installs/xdg-cache/go-build/79/79c1ef6ca28dfe2baa30df5b91f84a343054b0e85ac3e15b71cbbd66bf930ee9-a b/.cell-installs/xdg-cache/go-build/79/79c1ef6ca28dfe2baa30df5b91f84a343054b0e85ac3e15b71cbbd66bf930ee9-a
new file mode 100644
index 0000000..f2da8e4
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/79/79c1ef6ca28dfe2baa30df5b91f84a343054b0e85ac3e15b71cbbd66bf930ee9-a
@@ -0,0 +1 @@
+v1 79c1ef6ca28dfe2baa30df5b91f84a343054b0e85ac3e15b71cbbd66bf930ee9 03daaa7d05d0a2d9744a42bc21d6bdc779fa0ed254cbf79877d9d14b856cca62               311670  1787953569911625880
diff --git a/.cell-installs/xdg-cache/go-build/79/79c80a7750507b2c3d84a9cb4dba7db58bc2e965ed5ff456eb8bab03b98ec6fe-a b/.cell-installs/xdg-cache/go-build/79/79c80a7750507b2c3d84a9cb4dba7db58bc2e965ed5ff456eb8bab03b98ec6fe-a
new file mode 100644
index 0000000..7c1f754
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/79/79c80a7750507b2c3d84a9cb4dba7db58bc2e965ed5ff456eb8bab03b98ec6fe-a
@@ -0,0 +1 @@
+v1 79c80a7750507b2c3d84a9cb4dba7db58bc2e965ed5ff456eb8bab03b98ec6fe e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569915102451
diff --git a/.cell-installs/xdg-cache/go-build/79/79e345b89ac1ecaa0bb9bce77c06365f69ecc42eaa6ae78c7d833dc777f6fffb-d b/.cell-installs/xdg-cache/go-build/79/79e345b89ac1ecaa0bb9bce77c06365f69ecc42eaa6ae78c7d833dc777f6fffb-d
new file mode 100644
index 0000000..2bf6efc
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/79/79e345b89ac1ecaa0bb9bce77c06365f69ecc42eaa6ae78c7d833dc777f6fffb-d
@@ -0,0 +1,4 @@
+./slices.go
+./sort.go
+./zsortanyfunc.go
+./zsortordered.go
diff --git a/.cell-installs/xdg-cache/go-build/79/79eb4308563e9b15e694316dd01b4ec73d356842385cb143d05226a2251a7f0e-a b/.cell-installs/xdg-cache/go-build/79/79eb4308563e9b15e694316dd01b4ec73d356842385cb143d05226a2251a7f0e-a
new file mode 100644
index 0000000..a647199
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/79/79eb4308563e9b15e694316dd01b4ec73d356842385cb143d05226a2251a7f0e-a
@@ -0,0 +1 @@
+v1 79eb4308563e9b15e694316dd01b4ec73d356842385cb143d05226a2251a7f0e e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569566702790
diff --git a/.cell-installs/xdg-cache/go-build/79/79f7c61ad8480d475d3b2b227b06a02b3678b27ba92fa24016f36fb81027bece-a b/.cell-installs/xdg-cache/go-build/79/79f7c61ad8480d475d3b2b227b06a02b3678b27ba92fa24016f36fb81027bece-a
new file mode 100644
index 0000000..3df3d67
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/79/79f7c61ad8480d475d3b2b227b06a02b3678b27ba92fa24016f36fb81027bece-a
@@ -0,0 +1 @@
+v1 79f7c61ad8480d475d3b2b227b06a02b3678b27ba92fa24016f36fb81027bece 4f810f99d802ae3d07a1091ed6f79ea384dbd3d3c5a9e4fa243db3ea1935dd18                  920  1787953771571346965
diff --git a/.cell-installs/xdg-cache/go-build/7a/7a1c44a11969b2cde317a86d8fd7d7c53d1a5e460fc5c40662561c747e816144-d b/.cell-installs/xdg-cache/go-build/7a/7a1c44a11969b2cde317a86d8fd7d7c53d1a5e460fc5c40662561c747e816144-d
new file mode 100644
index 0000000..f4a0db0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/7a/7a1c44a11969b2cde317a86d8fd7d7c53d1a5e460fc5c40662561c747e816144-d
@@ -0,0 +1 @@
+./rtcov.go
diff --git a/.cell-installs/xdg-cache/go-build/7a/7a7a32868907972cdb1f764b317c14475cc898808097c7e74d4c9487143d2052-a b/.cell-installs/xdg-cache/go-build/7a/7a7a32868907972cdb1f764b317c14475cc898808097c7e74d4c9487143d2052-a
new file mode 100644
index 0000000..f4984f6
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/7a/7a7a32868907972cdb1f764b317c14475cc898808097c7e74d4c9487143d2052-a
@@ -0,0 +1 @@
+v1 7a7a32868907972cdb1f764b317c14475cc898808097c7e74d4c9487143d2052 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569259946290
diff --git a/.cell-installs/xdg-cache/go-build/7a/7ace44d1bb2fe529b781fb8ad48e54c03a5cafe5665ca8b8a31adef5f4a7dca0-d b/.cell-installs/xdg-cache/go-build/7a/7ace44d1bb2fe529b781fb8ad48e54c03a5cafe5665ca8b8a31adef5f4a7dca0-d
new file mode 100644
index 0000000..6b7c464
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/7a/7ace44d1bb2fe529b781fb8ad48e54c03a5cafe5665ca8b8a31adef5f4a7dca0-d differ
diff --git a/.cell-installs/xdg-cache/go-build/7b/7bf148f70b8b55cb2dab3ecfde5aaf0ea9beddce8d646fbb740beac985483f1b-a b/.cell-installs/xdg-cache/go-build/7b/7bf148f70b8b55cb2dab3ecfde5aaf0ea9beddce8d646fbb740beac985483f1b-a
new file mode 100644
index 0000000..5e785de
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/7b/7bf148f70b8b55cb2dab3ecfde5aaf0ea9beddce8d646fbb740beac985483f1b-a
@@ -0,0 +1 @@
+v1 7bf148f70b8b55cb2dab3ecfde5aaf0ea9beddce8d646fbb740beac985483f1b e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569988970461
diff --git a/.cell-installs/xdg-cache/go-build/7c/7c5093ddf9c5bd71ee82cbd24a6ae7d3a12ce14a25ce055383eeca80186acc1d-d b/.cell-installs/xdg-cache/go-build/7c/7c5093ddf9c5bd71ee82cbd24a6ae7d3a12ce14a25ce055383eeca80186acc1d-d
new file mode 100644
index 0000000..33a022e
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/7c/7c5093ddf9c5bd71ee82cbd24a6ae7d3a12ce14a25ce055383eeca80186acc1d-d differ
diff --git a/.cell-installs/xdg-cache/go-build/7c/7c6590eb7120d0c4caca81e7ade29301261b0cdc82359478dde0e7c44ab55032-a b/.cell-installs/xdg-cache/go-build/7c/7c6590eb7120d0c4caca81e7ade29301261b0cdc82359478dde0e7c44ab55032-a
new file mode 100644
index 0000000..6f52570
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/7c/7c6590eb7120d0c4caca81e7ade29301261b0cdc82359478dde0e7c44ab55032-a
@@ -0,0 +1 @@
+v1 7c6590eb7120d0c4caca81e7ade29301261b0cdc82359478dde0e7c44ab55032 963346a3c512f8c4ef1e4c2f20df20cb87f4e98534cd857413506334b6ed73ad               220086  1787953569260531822
diff --git a/.cell-installs/xdg-cache/go-build/7c/7c8d2fb1bc5a617787f66060a63bf935718c640bb2c12a03825b2e34bc3f57d6-a b/.cell-installs/xdg-cache/go-build/7c/7c8d2fb1bc5a617787f66060a63bf935718c640bb2c12a03825b2e34bc3f57d6-a
new file mode 100644
index 0000000..9077915
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/7c/7c8d2fb1bc5a617787f66060a63bf935718c640bb2c12a03825b2e34bc3f57d6-a
@@ -0,0 +1 @@
+v1 7c8d2fb1bc5a617787f66060a63bf935718c640bb2c12a03825b2e34bc3f57d6 f416aff38047cab648129e9819c6527a9ad2fec54a65692a965e29b24b2d8bc9                  276  1787953570176730008
diff --git a/.cell-installs/xdg-cache/go-build/7c/7c9b26c0d941e72df937d5bfcf6a7557e81d9849a37b7ca1b6e55d3f8607d921-d b/.cell-installs/xdg-cache/go-build/7c/7c9b26c0d941e72df937d5bfcf6a7557e81d9849a37b7ca1b6e55d3f8607d921-d
new file mode 100644
index 0000000..f39a6cd
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/7c/7c9b26c0d941e72df937d5bfcf6a7557e81d9849a37b7ca1b6e55d3f8607d921-d differ
diff --git a/.cell-installs/xdg-cache/go-build/7c/7ccbc779ad26b1b2a2236e142440cd26fa54504420cdb9400cc8a18617b5086f-d b/.cell-installs/xdg-cache/go-build/7c/7ccbc779ad26b1b2a2236e142440cd26fa54504420cdb9400cc8a18617b5086f-d
new file mode 100644
index 0000000..14b66c6
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/7c/7ccbc779ad26b1b2a2236e142440cd26fa54504420cdb9400cc8a18617b5086f-d differ
diff --git a/.cell-installs/xdg-cache/go-build/7c/7cfa5642e447fe8533a2eb28caaf0d112efad6204677fbddf69df1989ec922d8-a b/.cell-installs/xdg-cache/go-build/7c/7cfa5642e447fe8533a2eb28caaf0d112efad6204677fbddf69df1989ec922d8-a
new file mode 100644
index 0000000..2e32436
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/7c/7cfa5642e447fe8533a2eb28caaf0d112efad6204677fbddf69df1989ec922d8-a
@@ -0,0 +1 @@
+v1 7cfa5642e447fe8533a2eb28caaf0d112efad6204677fbddf69df1989ec922d8 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953919154773053
diff --git a/.cell-installs/xdg-cache/go-build/7d/7de859f2fabcd300bd04944ce852c8f0d3fe0c3d6770b39d2406d3e2fac617b5-a b/.cell-installs/xdg-cache/go-build/7d/7de859f2fabcd300bd04944ce852c8f0d3fe0c3d6770b39d2406d3e2fac617b5-a
new file mode 100644
index 0000000..5228ec1
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/7d/7de859f2fabcd300bd04944ce852c8f0d3fe0c3d6770b39d2406d3e2fac617b5-a
@@ -0,0 +1 @@
+v1 7de859f2fabcd300bd04944ce852c8f0d3fe0c3d6770b39d2406d3e2fac617b5 b01a5dbb90a7da0a59b39f3442bbba455cd182ff509ecdf8e2475f6135376acc                  180  1787953570185202952
diff --git a/.cell-installs/xdg-cache/go-build/7e/7e86e37b4e9350d1955add7e4b2ca9e6cbfa4d7c16aa51c13d341681961478db-a b/.cell-installs/xdg-cache/go-build/7e/7e86e37b4e9350d1955add7e4b2ca9e6cbfa4d7c16aa51c13d341681961478db-a
new file mode 100644
index 0000000..09fff5b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/7e/7e86e37b4e9350d1955add7e4b2ca9e6cbfa4d7c16aa51c13d341681961478db-a
@@ -0,0 +1 @@
+v1 7e86e37b4e9350d1955add7e4b2ca9e6cbfa4d7c16aa51c13d341681961478db e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569875256127
diff --git a/.cell-installs/xdg-cache/go-build/7e/7eacbd0cb1ffeecc9171db8b35a492b8de4ba9038bbfb7f3e7b70555caec7e58-d b/.cell-installs/xdg-cache/go-build/7e/7eacbd0cb1ffeecc9171db8b35a492b8de4ba9038bbfb7f3e7b70555caec7e58-d
new file mode 100644
index 0000000..31aff20
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/7e/7eacbd0cb1ffeecc9171db8b35a492b8de4ba9038bbfb7f3e7b70555caec7e58-d differ
diff --git a/.cell-installs/xdg-cache/go-build/7e/7edee121e00ad962998899746a6fe47c76bf217d95cf569e292285225d18ef91-d b/.cell-installs/xdg-cache/go-build/7e/7edee121e00ad962998899746a6fe47c76bf217d95cf569e292285225d18ef91-d
new file mode 100644
index 0000000..b83fbcd
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/7e/7edee121e00ad962998899746a6fe47c76bf217d95cf569e292285225d18ef91-d differ
diff --git a/.cell-installs/xdg-cache/go-build/7f/7f1a40da983c44a1cc46724b73a2f01e54dba954ca711e509d5294a36ea88461-a b/.cell-installs/xdg-cache/go-build/7f/7f1a40da983c44a1cc46724b73a2f01e54dba954ca711e509d5294a36ea88461-a
new file mode 100644
index 0000000..058ac16
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/7f/7f1a40da983c44a1cc46724b73a2f01e54dba954ca711e509d5294a36ea88461-a
@@ -0,0 +1 @@
+v1 7f1a40da983c44a1cc46724b73a2f01e54dba954ca711e509d5294a36ea88461 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569915844284
diff --git a/.cell-installs/xdg-cache/go-build/7f/7f939f8803bdcecd0408a5f7c7fb0755a7973a2a9c32373718691800942efb73-a b/.cell-installs/xdg-cache/go-build/7f/7f939f8803bdcecd0408a5f7c7fb0755a7973a2a9c32373718691800942efb73-a
new file mode 100644
index 0000000..e246aed
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/7f/7f939f8803bdcecd0408a5f7c7fb0755a7973a2a9c32373718691800942efb73-a
@@ -0,0 +1 @@
+v1 7f939f8803bdcecd0408a5f7c7fb0755a7973a2a9c32373718691800942efb73 4083f51d30100984bc476511835728906849353484dbfc991f25cf8ad53e75e4                 5685  1787953153930696305
diff --git a/.cell-installs/xdg-cache/go-build/80/8011e9c53622e4ccba7d311ba870ce1ae1444a4269e0abb0ba08e9582806ae4f-d b/.cell-installs/xdg-cache/go-build/80/8011e9c53622e4ccba7d311ba870ce1ae1444a4269e0abb0ba08e9582806ae4f-d
new file mode 100644
index 0000000..1fbdc39
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/80/8011e9c53622e4ccba7d311ba870ce1ae1444a4269e0abb0ba08e9582806ae4f-d
@@ -0,0 +1,2 @@
+./sig.go
+./sig_amd64.s
diff --git a/.cell-installs/xdg-cache/go-build/80/802a0baf2d8a2ee99b95f7f11a995ebb7912a8fd7c9e862ed69a899dac040948-a b/.cell-installs/xdg-cache/go-build/80/802a0baf2d8a2ee99b95f7f11a995ebb7912a8fd7c9e862ed69a899dac040948-a
new file mode 100644
index 0000000..05b1047
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/80/802a0baf2d8a2ee99b95f7f11a995ebb7912a8fd7c9e862ed69a899dac040948-a
@@ -0,0 +1 @@
+v1 802a0baf2d8a2ee99b95f7f11a995ebb7912a8fd7c9e862ed69a899dac040948 8cc7b333d5ca7990be774b5eaf6497dca0301093c1d2e8bbd93de5ba1c14528c                  537  1787953170150521155
diff --git a/.cell-installs/xdg-cache/go-build/80/805809a2e629397aca7604449319b1b38366631493593b9ee174a13c6ea607a1-a b/.cell-installs/xdg-cache/go-build/80/805809a2e629397aca7604449319b1b38366631493593b9ee174a13c6ea607a1-a
new file mode 100644
index 0000000..7dd0b98
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/80/805809a2e629397aca7604449319b1b38366631493593b9ee174a13c6ea607a1-a
@@ -0,0 +1 @@
+v1 805809a2e629397aca7604449319b1b38366631493593b9ee174a13c6ea607a1 0f8693e97405a6b15dbe4b3bf10f0c2fe3b71cceef7660c4cf56f6978d7da5c2                  201  1787953170153154012
diff --git a/.cell-installs/xdg-cache/go-build/80/80845c6a5bcc4d5397f80b465aa6979b9fa01b31b7b9b46a55b08d6d8f082d2a-a b/.cell-installs/xdg-cache/go-build/80/80845c6a5bcc4d5397f80b465aa6979b9fa01b31b7b9b46a55b08d6d8f082d2a-a
new file mode 100644
index 0000000..9d2250f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/80/80845c6a5bcc4d5397f80b465aa6979b9fa01b31b7b9b46a55b08d6d8f082d2a-a
@@ -0,0 +1 @@
+v1 80845c6a5bcc4d5397f80b465aa6979b9fa01b31b7b9b46a55b08d6d8f082d2a 0a1c58563cdfc288b32d4896f8ac10962de34b1d3300ad3e304cb76055d04d1b               658964  1787953569144564337
diff --git a/.cell-installs/xdg-cache/go-build/80/80cb8158f655f33ebfe81a7915cd40e591873a7efad630685e3b1f5439268c19-d b/.cell-installs/xdg-cache/go-build/80/80cb8158f655f33ebfe81a7915cd40e591873a7efad630685e3b1f5439268c19-d
new file mode 100644
index 0000000..98d46d2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/80/80cb8158f655f33ebfe81a7915cd40e591873a7efad630685e3b1f5439268c19-d
@@ -0,0 +1 @@
+./context.go
diff --git a/.cell-installs/xdg-cache/go-build/80/80df895ce34aed241743e8781802b13a4f6a90b03bf5b9c1392302d7a4d7acba-d b/.cell-installs/xdg-cache/go-build/80/80df895ce34aed241743e8781802b13a4f6a90b03bf5b9c1392302d7a4d7acba-d
new file mode 100644
index 0000000..7ef26ef
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/80/80df895ce34aed241743e8781802b13a4f6a90b03bf5b9c1392302d7a4d7acba-d
@@ -0,0 +1,15 @@
+./at.go
+./at_fstatat.go
+./at_sysnum_linux.go
+./at_sysnum_newfstatat_linux.go
+./constants.go
+./copy_file_range_linux.go
+./eaccess_linux.go
+./fcntl_unix.go
+./getrandom.go
+./getrandom_linux.go
+./kernel_version_linux.go
+./net.go
+./nonblocking_unix.go
+./pidfd_linux.go
+./sysnum_linux_amd64.go
diff --git a/.cell-installs/xdg-cache/go-build/81/811a8fa82ebb2ea19a98b5fde95a47bd932e6ee791652aeeae7b7bb0dd674ece-d b/.cell-installs/xdg-cache/go-build/81/811a8fa82ebb2ea19a98b5fde95a47bd932e6ee791652aeeae7b7bb0dd674ece-d
new file mode 100644
index 0000000..1449869
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/81/811a8fa82ebb2ea19a98b5fde95a47bd932e6ee791652aeeae7b7bb0dd674ece-d differ
diff --git a/.cell-installs/xdg-cache/go-build/81/812790363b4d2ed938a5e8885c30d111ef62d44b9ab49b20ec344a73cc3a34e8-d b/.cell-installs/xdg-cache/go-build/81/812790363b4d2ed938a5e8885c30d111ef62d44b9ab49b20ec344a73cc3a34e8-d
new file mode 100644
index 0000000..e67825d
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/81/812790363b4d2ed938a5e8885c30d111ef62d44b9ab49b20ec344a73cc3a34e8-d differ
diff --git a/.cell-installs/xdg-cache/go-build/81/817d764c0c9369a93d7efcd16244d675859cf670a074c23e4b564a4810331878-d b/.cell-installs/xdg-cache/go-build/81/817d764c0c9369a93d7efcd16244d675859cf670a074c23e4b564a4810331878-d
new file mode 100644
index 0000000..ac38494
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/81/817d764c0c9369a93d7efcd16244d675859cf670a074c23e4b564a4810331878-d differ
diff --git a/.cell-installs/xdg-cache/go-build/81/818cfd928ec48650e3b1ebeabf765eb102c9f0896362da49681540fc45b6d513-a b/.cell-installs/xdg-cache/go-build/81/818cfd928ec48650e3b1ebeabf765eb102c9f0896362da49681540fc45b6d513-a
new file mode 100644
index 0000000..1982931
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/81/818cfd928ec48650e3b1ebeabf765eb102c9f0896362da49681540fc45b6d513-a
@@ -0,0 +1 @@
+v1 818cfd928ec48650e3b1ebeabf765eb102c9f0896362da49681540fc45b6d513 89bbb894ee96210a6a2c3f7ef8e828df23c153b12e1d0801e9491a0b45f62e8e                 1671  1787953170154702011
diff --git a/.cell-installs/xdg-cache/go-build/81/81ba8242341c2d3c2c97601a70f86678ff95fb28461448d90d871f45cd2f19e8-a b/.cell-installs/xdg-cache/go-build/81/81ba8242341c2d3c2c97601a70f86678ff95fb28461448d90d871f45cd2f19e8-a
new file mode 100644
index 0000000..f26fd70
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/81/81ba8242341c2d3c2c97601a70f86678ff95fb28461448d90d871f45cd2f19e8-a
@@ -0,0 +1 @@
+v1 81ba8242341c2d3c2c97601a70f86678ff95fb28461448d90d871f45cd2f19e8 e1f4928a75355573e92499d4ab842fde5cdc23fe7dc03967d6a4ca5c634ab18b                   32  1787953569235826358
diff --git a/.cell-installs/xdg-cache/go-build/82/82a9daa238cab3dc522c2f9d5dfe19db8e3fe5993f7b837b3e10d57d73d85010-a b/.cell-installs/xdg-cache/go-build/82/82a9daa238cab3dc522c2f9d5dfe19db8e3fe5993f7b837b3e10d57d73d85010-a
new file mode 100644
index 0000000..74dfef4
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/82/82a9daa238cab3dc522c2f9d5dfe19db8e3fe5993f7b837b3e10d57d73d85010-a
@@ -0,0 +1 @@
+v1 82a9daa238cab3dc522c2f9d5dfe19db8e3fe5993f7b837b3e10d57d73d85010 291a43954ff94e4fb31e12ad0114ebe6e52f5043ed257757f6d6a45911cfa586                63534  1787953567809190046
diff --git a/.cell-installs/xdg-cache/go-build/82/82c5b94429bd84416b09a42ccc3283ac72321240b0ad12b9686840c6fbb0fc15-d b/.cell-installs/xdg-cache/go-build/82/82c5b94429bd84416b09a42ccc3283ac72321240b0ad12b9686840c6fbb0fc15-d
new file mode 100644
index 0000000..8b982f8
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/82/82c5b94429bd84416b09a42ccc3283ac72321240b0ad12b9686840c6fbb0fc15-d differ
diff --git a/.cell-installs/xdg-cache/go-build/82/82c89db103e0419e127625186e32820d17e3be4f9438a6c56a7cdae44bccb538-a b/.cell-installs/xdg-cache/go-build/82/82c89db103e0419e127625186e32820d17e3be4f9438a6c56a7cdae44bccb538-a
new file mode 100644
index 0000000..fd3fd20
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/82/82c89db103e0419e127625186e32820d17e3be4f9438a6c56a7cdae44bccb538-a
@@ -0,0 +1 @@
+v1 82c89db103e0419e127625186e32820d17e3be4f9438a6c56a7cdae44bccb538 ef7dba45581dd71721816a4ca086bfe9e3db5f54f2a5b1d71208acf69483d79b                  140  1787953170160400771
diff --git a/.cell-installs/xdg-cache/go-build/82/82d49d1aa2b5f993e32120945d8929f14f6d329ce392a12c89717ebb4ad1723e-a b/.cell-installs/xdg-cache/go-build/82/82d49d1aa2b5f993e32120945d8929f14f6d329ce392a12c89717ebb4ad1723e-a
new file mode 100644
index 0000000..6abcf51
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/82/82d49d1aa2b5f993e32120945d8929f14f6d329ce392a12c89717ebb4ad1723e-a
@@ -0,0 +1 @@
+v1 82d49d1aa2b5f993e32120945d8929f14f6d329ce392a12c89717ebb4ad1723e 6d4682df2feb881f0f88308949ef264fd934db774324176b9fc38bd940f0b5ce                 2466  1787953567789726956
diff --git a/.cell-installs/xdg-cache/go-build/83/830e06d9b0a0005e03ffc34da06ec8452e2d981a0850d67ced4c5a18d18f6046-d b/.cell-installs/xdg-cache/go-build/83/830e06d9b0a0005e03ffc34da06ec8452e2d981a0850d67ced4c5a18d18f6046-d
new file mode 100644
index 0000000..518cd58
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/83/830e06d9b0a0005e03ffc34da06ec8452e2d981a0850d67ced4c5a18d18f6046-d differ
diff --git a/.cell-installs/xdg-cache/go-build/83/8318c3a6d28c34f2da8a316ff95558632b51ed3cccfd1d21c202a4301e0354ea-d b/.cell-installs/xdg-cache/go-build/83/8318c3a6d28c34f2da8a316ff95558632b51ed3cccfd1d21c202a4301e0354ea-d
new file mode 100644
index 0000000..acff22c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/83/8318c3a6d28c34f2da8a316ff95558632b51ed3cccfd1d21c202a4301e0354ea-d differ
diff --git a/.cell-installs/xdg-cache/go-build/83/83420e35e4d4f7e84eb32eb5842fa882e1adc274bfb187a73aa0548ac68f2ddd-a b/.cell-installs/xdg-cache/go-build/83/83420e35e4d4f7e84eb32eb5842fa882e1adc274bfb187a73aa0548ac68f2ddd-a
new file mode 100644
index 0000000..35c93c2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/83/83420e35e4d4f7e84eb32eb5842fa882e1adc274bfb187a73aa0548ac68f2ddd-a
@@ -0,0 +1 @@
+v1 83420e35e4d4f7e84eb32eb5842fa882e1adc274bfb187a73aa0548ac68f2ddd e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569923632630
diff --git a/.cell-installs/xdg-cache/go-build/83/837f538ea7f29cc17fcae5fe806539ecc7203d0b5abfdfa6b8b12b1da577c2d8-a b/.cell-installs/xdg-cache/go-build/83/837f538ea7f29cc17fcae5fe806539ecc7203d0b5abfdfa6b8b12b1da577c2d8-a
new file mode 100644
index 0000000..db16af0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/83/837f538ea7f29cc17fcae5fe806539ecc7203d0b5abfdfa6b8b12b1da577c2d8-a
@@ -0,0 +1 @@
+v1 837f538ea7f29cc17fcae5fe806539ecc7203d0b5abfdfa6b8b12b1da577c2d8 0c6f5b0ae57581d106c1fdc1565c95a881c781a5d079895f896ecd3b6431382a                  660  1787953170193058268
diff --git a/.cell-installs/xdg-cache/go-build/83/838496ebd75ab44388509baa9eac8dec8b082d69a49d3938a391c3b546a4ea0a-a b/.cell-installs/xdg-cache/go-build/83/838496ebd75ab44388509baa9eac8dec8b082d69a49d3938a391c3b546a4ea0a-a
new file mode 100644
index 0000000..d5c7d68
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/83/838496ebd75ab44388509baa9eac8dec8b082d69a49d3938a391c3b546a4ea0a-a
@@ -0,0 +1 @@
+v1 838496ebd75ab44388509baa9eac8dec8b082d69a49d3938a391c3b546a4ea0a e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569921000697
diff --git a/.cell-installs/xdg-cache/go-build/83/83938ce5a466bdbbae6dd81f6ac96c9ba10ee669d5de94132173d49ea03b5581-a b/.cell-installs/xdg-cache/go-build/83/83938ce5a466bdbbae6dd81f6ac96c9ba10ee669d5de94132173d49ea03b5581-a
new file mode 100644
index 0000000..bce3977
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/83/83938ce5a466bdbbae6dd81f6ac96c9ba10ee669d5de94132173d49ea03b5581-a
@@ -0,0 +1 @@
+v1 83938ce5a466bdbbae6dd81f6ac96c9ba10ee669d5de94132173d49ea03b5581 6a0c5fcd36302f3907f7842cd08ebc67bdd8908b919d15ff4c84bb6b66eefc79                 3653  1787953771572148219
diff --git a/.cell-installs/xdg-cache/go-build/83/83c8f5acd0e69258665757425cef3fc989f2e9e4abca4f9cc91549b287d245d4-a b/.cell-installs/xdg-cache/go-build/83/83c8f5acd0e69258665757425cef3fc989f2e9e4abca4f9cc91549b287d245d4-a
new file mode 100644
index 0000000..73fbb89
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/83/83c8f5acd0e69258665757425cef3fc989f2e9e4abca4f9cc91549b287d245d4-a
@@ -0,0 +1 @@
+v1 83c8f5acd0e69258665757425cef3fc989f2e9e4abca4f9cc91549b287d245d4 bd31440aba755b3c279e4ab053b413a45614e4fa1a14e5233af5d611284d6cda                 4516  1787953170194019266
diff --git a/.cell-installs/xdg-cache/go-build/84/841b7ad469976e56a4fd4b8d9ef5a3160c20be52cf55eb24e39e3e3d5fc4e686-a b/.cell-installs/xdg-cache/go-build/84/841b7ad469976e56a4fd4b8d9ef5a3160c20be52cf55eb24e39e3e3d5fc4e686-a
new file mode 100644
index 0000000..31c03b8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/84/841b7ad469976e56a4fd4b8d9ef5a3160c20be52cf55eb24e39e3e3d5fc4e686-a
@@ -0,0 +1 @@
+v1 841b7ad469976e56a4fd4b8d9ef5a3160c20be52cf55eb24e39e3e3d5fc4e686 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569118476655
diff --git a/.cell-installs/xdg-cache/go-build/84/841e117e57e58a473e7a9e06920d1a1ac287c2493d59a2d1268771e4be176a12-a b/.cell-installs/xdg-cache/go-build/84/841e117e57e58a473e7a9e06920d1a1ac287c2493d59a2d1268771e4be176a12-a
new file mode 100644
index 0000000..7ee013b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/84/841e117e57e58a473e7a9e06920d1a1ac287c2493d59a2d1268771e4be176a12-a
@@ -0,0 +1 @@
+v1 841e117e57e58a473e7a9e06920d1a1ac287c2493d59a2d1268771e4be176a12 f5af47691b4c804b373b947595ee26ab1bac9fe817cd4070f2411b2f1d9a4b78                   11  1787953569867088308
diff --git a/.cell-installs/xdg-cache/go-build/84/8483c34f1539c0e021362d715887d6ba0ad1ddd89490491327daed66fe8dc1d2-a b/.cell-installs/xdg-cache/go-build/84/8483c34f1539c0e021362d715887d6ba0ad1ddd89490491327daed66fe8dc1d2-a
new file mode 100644
index 0000000..8b06300
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/84/8483c34f1539c0e021362d715887d6ba0ad1ddd89490491327daed66fe8dc1d2-a
@@ -0,0 +1 @@
+v1 8483c34f1539c0e021362d715887d6ba0ad1ddd89490491327daed66fe8dc1d2 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570335496412
diff --git a/.cell-installs/xdg-cache/go-build/84/84cbdd1dc75577958e175b314bb9a1d9227f024765b340125f97a9443e0874ba-a b/.cell-installs/xdg-cache/go-build/84/84cbdd1dc75577958e175b314bb9a1d9227f024765b340125f97a9443e0874ba-a
new file mode 100644
index 0000000..b7de35b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/84/84cbdd1dc75577958e175b314bb9a1d9227f024765b340125f97a9443e0874ba-a
@@ -0,0 +1 @@
+v1 84cbdd1dc75577958e175b314bb9a1d9227f024765b340125f97a9443e0874ba 578586d15c0423bfb4145692871f6d950929b8f7e47d193a97031a7a973b58f6                 6170  1787953568826988096
diff --git a/.cell-installs/xdg-cache/go-build/84/84d6c19c592587e29abd693fd9ddb3124f0a5ee5025f84fc70d05bd1b5dac2e4-a b/.cell-installs/xdg-cache/go-build/84/84d6c19c592587e29abd693fd9ddb3124f0a5ee5025f84fc70d05bd1b5dac2e4-a
new file mode 100644
index 0000000..179fe9f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/84/84d6c19c592587e29abd693fd9ddb3124f0a5ee5025f84fc70d05bd1b5dac2e4-a
@@ -0,0 +1 @@
+v1 84d6c19c592587e29abd693fd9ddb3124f0a5ee5025f84fc70d05bd1b5dac2e4 e6ca2ff2127b18a3433da89c097372c108b814f87e9fabca861d88fc2fa8193c                 3439  1787953170160693047
diff --git a/.cell-installs/xdg-cache/go-build/84/84fa283cd7700b86cdf1228f3b9bc4531918c10de197ab7047e458338b4ef39c-a b/.cell-installs/xdg-cache/go-build/84/84fa283cd7700b86cdf1228f3b9bc4531918c10de197ab7047e458338b4ef39c-a
new file mode 100644
index 0000000..9df439f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/84/84fa283cd7700b86cdf1228f3b9bc4531918c10de197ab7047e458338b4ef39c-a
@@ -0,0 +1 @@
+v1 84fa283cd7700b86cdf1228f3b9bc4531918c10de197ab7047e458338b4ef39c e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567797512768
diff --git a/.cell-installs/xdg-cache/go-build/85/8501ea793151b1b9aedcd711cb27a44997ca65ae56a59afc02921571729d9dc0-d b/.cell-installs/xdg-cache/go-build/85/8501ea793151b1b9aedcd711cb27a44997ca65ae56a59afc02921571729d9dc0-d
new file mode 100644
index 0000000..c11020c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/85/8501ea793151b1b9aedcd711cb27a44997ca65ae56a59afc02921571729d9dc0-d differ
diff --git a/.cell-installs/xdg-cache/go-build/85/85088353d860a3d2a6fbccb40cad2fc97991ee4c1c2759c8597e78be81e9b7ab-d b/.cell-installs/xdg-cache/go-build/85/85088353d860a3d2a6fbccb40cad2fc97991ee4c1c2759c8597e78be81e9b7ab-d
new file mode 100644
index 0000000..e2c8c12
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/85/85088353d860a3d2a6fbccb40cad2fc97991ee4c1c2759c8597e78be81e9b7ab-d differ
diff --git a/.cell-installs/xdg-cache/go-build/85/85488a5182cd33087b9cc3512e33e54c012d24320e3e87d8d0024143dcfbe35a-a b/.cell-installs/xdg-cache/go-build/85/85488a5182cd33087b9cc3512e33e54c012d24320e3e87d8d0024143dcfbe35a-a
new file mode 100644
index 0000000..6bbc2cf
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/85/85488a5182cd33087b9cc3512e33e54c012d24320e3e87d8d0024143dcfbe35a-a
@@ -0,0 +1 @@
+v1 85488a5182cd33087b9cc3512e33e54c012d24320e3e87d8d0024143dcfbe35a e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569318050506
diff --git a/.cell-installs/xdg-cache/go-build/85/8564466451891c91952fa95cd49d20687cbc05ab9920bc3d852d22c45009c188-a b/.cell-installs/xdg-cache/go-build/85/8564466451891c91952fa95cd49d20687cbc05ab9920bc3d852d22c45009c188-a
new file mode 100644
index 0000000..f993142
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/85/8564466451891c91952fa95cd49d20687cbc05ab9920bc3d852d22c45009c188-a
@@ -0,0 +1 @@
+v1 8564466451891c91952fa95cd49d20687cbc05ab9920bc3d852d22c45009c188 86adbbb15c53775a99f62697b7e04b4648ccd5ae09c2ebf3916c7f1aa915148c                  535  1787953354451771607
diff --git a/.cell-installs/xdg-cache/go-build/85/857765ccba8c0066dda257e49671d94481789afe80643c5552ee6c6669fb2c59-a b/.cell-installs/xdg-cache/go-build/85/857765ccba8c0066dda257e49671d94481789afe80643c5552ee6c6669fb2c59-a
new file mode 100644
index 0000000..4c071a2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/85/857765ccba8c0066dda257e49671d94481789afe80643c5552ee6c6669fb2c59-a
@@ -0,0 +1 @@
+v1 857765ccba8c0066dda257e49671d94481789afe80643c5552ee6c6669fb2c59 6032fad5a4da6049c6af1f93024c8442779e0511ff8e884935f0eeede2f7d1ee                  144  1787953170150057946
diff --git a/.cell-installs/xdg-cache/go-build/86/86344d5c905c7a3cd36549cd089af7c53e1e0151d25b64f3ac88d1811f9b0c45-d b/.cell-installs/xdg-cache/go-build/86/86344d5c905c7a3cd36549cd089af7c53e1e0151d25b64f3ac88d1811f9b0c45-d
new file mode 100644
index 0000000..064e16d
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/86/86344d5c905c7a3cd36549cd089af7c53e1e0151d25b64f3ac88d1811f9b0c45-d differ
diff --git a/.cell-installs/xdg-cache/go-build/86/8675c40bae9c1de8423101e5c18feb8bd4914ac3453837aaf022b46af661290c-d b/.cell-installs/xdg-cache/go-build/86/8675c40bae9c1de8423101e5c18feb8bd4914ac3453837aaf022b46af661290c-d
new file mode 100644
index 0000000..b3d356c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/86/8675c40bae9c1de8423101e5c18feb8bd4914ac3453837aaf022b46af661290c-d differ
diff --git a/.cell-installs/xdg-cache/go-build/86/86a4ac26b97474c4ca9261ef0bc47066b8bbf24255922dd59b6de4dc681ab20d-a b/.cell-installs/xdg-cache/go-build/86/86a4ac26b97474c4ca9261ef0bc47066b8bbf24255922dd59b6de4dc681ab20d-a
new file mode 100644
index 0000000..3d55069
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/86/86a4ac26b97474c4ca9261ef0bc47066b8bbf24255922dd59b6de4dc681ab20d-a
@@ -0,0 +1 @@
+v1 86a4ac26b97474c4ca9261ef0bc47066b8bbf24255922dd59b6de4dc681ab20d ecb2c4985460bc939dc082545e1c986ae9a05b5f8be77a27862fdfa1ff6ef7f0                  664  1787953771570175826
diff --git a/.cell-installs/xdg-cache/go-build/86/86a6f813f73eaf51bd0e27fd38670ece8a78028f625f884dbb23cd6c7b959c28-d b/.cell-installs/xdg-cache/go-build/86/86a6f813f73eaf51bd0e27fd38670ece8a78028f625f884dbb23cd6c7b959c28-d
new file mode 100644
index 0000000..81ff4b4
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/86/86a6f813f73eaf51bd0e27fd38670ece8a78028f625f884dbb23cd6c7b959c28-d differ
diff --git a/.cell-installs/xdg-cache/go-build/86/86abb8148fda71a53a76de023d8bda3cb92c9122ca659d36b3d99b40c576e9e7-d b/.cell-installs/xdg-cache/go-build/86/86abb8148fda71a53a76de023d8bda3cb92c9122ca659d36b3d99b40c576e9e7-d
new file mode 100644
index 0000000..da1a2e5
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/86/86abb8148fda71a53a76de023d8bda3cb92c9122ca659d36b3d99b40c576e9e7-d differ
diff --git a/.cell-installs/xdg-cache/go-build/86/86adbbb15c53775a99f62697b7e04b4648ccd5ae09c2ebf3916c7f1aa915148c-d b/.cell-installs/xdg-cache/go-build/86/86adbbb15c53775a99f62697b7e04b4648ccd5ae09c2ebf3916c7f1aa915148c-d
new file mode 100644
index 0000000..489e6e4
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/86/86adbbb15c53775a99f62697b7e04b4648ccd5ae09c2ebf3916c7f1aa915148c-d differ
diff --git a/.cell-installs/xdg-cache/go-build/86/86fac65a16d58e1f6a66731acd825b98d52f3580fb50f60f6cb228399d4cacaa-a b/.cell-installs/xdg-cache/go-build/86/86fac65a16d58e1f6a66731acd825b98d52f3580fb50f60f6cb228399d4cacaa-a
new file mode 100644
index 0000000..12df813
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/86/86fac65a16d58e1f6a66731acd825b98d52f3580fb50f60f6cb228399d4cacaa-a
@@ -0,0 +1 @@
+v1 86fac65a16d58e1f6a66731acd825b98d52f3580fb50f60f6cb228399d4cacaa e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567787703372
diff --git a/.cell-installs/xdg-cache/go-build/87/872ebfa713f43f75af41cfac17d5055930ab7a0514597b6751bbded5c621168a-d b/.cell-installs/xdg-cache/go-build/87/872ebfa713f43f75af41cfac17d5055930ab7a0514597b6751bbded5c621168a-d
new file mode 100644
index 0000000..a1b3cd3
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/87/872ebfa713f43f75af41cfac17d5055930ab7a0514597b6751bbded5c621168a-d differ
diff --git a/.cell-installs/xdg-cache/go-build/87/87ad477ba46b8e72e9ac7410d8005c730930cee575b1d172230615676bb50cff-d b/.cell-installs/xdg-cache/go-build/87/87ad477ba46b8e72e9ac7410d8005c730930cee575b1d172230615676bb50cff-d
new file mode 100644
index 0000000..9586a77
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/87/87ad477ba46b8e72e9ac7410d8005c730930cee575b1d172230615676bb50cff-d differ
diff --git a/.cell-installs/xdg-cache/go-build/88/88093e39301c0f1b6a9abfae26798b1a22bffd0b4c8ead28614883c7cb68c478-d b/.cell-installs/xdg-cache/go-build/88/88093e39301c0f1b6a9abfae26798b1a22bffd0b4c8ead28614883c7cb68c478-d
new file mode 100644
index 0000000..70e2561
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/88/88093e39301c0f1b6a9abfae26798b1a22bffd0b4c8ead28614883c7cb68c478-d
@@ -0,0 +1,2 @@
+./annotation.go
+./trace.go
diff --git a/.cell-installs/xdg-cache/go-build/88/8880e8cf3d4ad02b27299d080787b1bf6b1646400c189a6b17f427a8446575ed-a b/.cell-installs/xdg-cache/go-build/88/8880e8cf3d4ad02b27299d080787b1bf6b1646400c189a6b17f427a8446575ed-a
new file mode 100644
index 0000000..ed0a035
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/88/8880e8cf3d4ad02b27299d080787b1bf6b1646400c189a6b17f427a8446575ed-a
@@ -0,0 +1 @@
+v1 8880e8cf3d4ad02b27299d080787b1bf6b1646400c189a6b17f427a8446575ed e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569142938798
diff --git a/.cell-installs/xdg-cache/go-build/88/88e230616ac1d082e1952afaf64a6ded7319217c1ac2b0c35794c4387381276e-d b/.cell-installs/xdg-cache/go-build/88/88e230616ac1d082e1952afaf64a6ded7319217c1ac2b0c35794c4387381276e-d
new file mode 100644
index 0000000..36be549
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/88/88e230616ac1d082e1952afaf64a6ded7319217c1ac2b0c35794c4387381276e-d differ
diff --git a/.cell-installs/xdg-cache/go-build/88/88ee093ab9e21bfcb70a47b53ca6ba25a3ed1b74ceb7099ce70f8f2b52ca3717-a b/.cell-installs/xdg-cache/go-build/88/88ee093ab9e21bfcb70a47b53ca6ba25a3ed1b74ceb7099ce70f8f2b52ca3717-a
new file mode 100644
index 0000000..22222a4
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/88/88ee093ab9e21bfcb70a47b53ca6ba25a3ed1b74ceb7099ce70f8f2b52ca3717-a
@@ -0,0 +1 @@
+v1 88ee093ab9e21bfcb70a47b53ca6ba25a3ed1b74ceb7099ce70f8f2b52ca3717 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569594846399
diff --git a/.cell-installs/xdg-cache/go-build/89/8978ecc8e0492192324ac7c0f4b9b8ebdc29a5cf945e289661e3c44b98d35f39-a b/.cell-installs/xdg-cache/go-build/89/8978ecc8e0492192324ac7c0f4b9b8ebdc29a5cf945e289661e3c44b98d35f39-a
new file mode 100644
index 0000000..42e30d3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/89/8978ecc8e0492192324ac7c0f4b9b8ebdc29a5cf945e289661e3c44b98d35f39-a
@@ -0,0 +1 @@
+v1 8978ecc8e0492192324ac7c0f4b9b8ebdc29a5cf945e289661e3c44b98d35f39 a07e525e78f00cc5e05f48e0e5b651b672a10e900ad2448ffc4009a6c0e83233                21022  1787953567796995483
diff --git a/.cell-installs/xdg-cache/go-build/89/89bbb894ee96210a6a2c3f7ef8e828df23c153b12e1d0801e9491a0b45f62e8e-d b/.cell-installs/xdg-cache/go-build/89/89bbb894ee96210a6a2c3f7ef8e828df23c153b12e1d0801e9491a0b45f62e8e-d
new file mode 100644
index 0000000..15098b8
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/89/89bbb894ee96210a6a2c3f7ef8e828df23c153b12e1d0801e9491a0b45f62e8e-d differ
diff --git a/.cell-installs/xdg-cache/go-build/89/89c7365dcbf8ecd392dd72eb8480f601d4064725cc35f1d9a2effe3d2b32ee71-a b/.cell-installs/xdg-cache/go-build/89/89c7365dcbf8ecd392dd72eb8480f601d4064725cc35f1d9a2effe3d2b32ee71-a
new file mode 100644
index 0000000..16869a7
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/89/89c7365dcbf8ecd392dd72eb8480f601d4064725cc35f1d9a2effe3d2b32ee71-a
@@ -0,0 +1 @@
+v1 89c7365dcbf8ecd392dd72eb8480f601d4064725cc35f1d9a2effe3d2b32ee71 538c92bc3645b6804d0a3d28277fe4f05a5724715bfa6b5cf8a61cd05853dd7f                   50  1787953569114722874
diff --git a/.cell-installs/xdg-cache/go-build/8a/8a690b7ee89b70556d6386e3e9c7e560674fd0d2ee810ed86bff94abe41bfd21-d b/.cell-installs/xdg-cache/go-build/8a/8a690b7ee89b70556d6386e3e9c7e560674fd0d2ee810ed86bff94abe41bfd21-d
new file mode 100644
index 0000000..b758665
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/8a/8a690b7ee89b70556d6386e3e9c7e560674fd0d2ee810ed86bff94abe41bfd21-d differ
diff --git a/.cell-installs/xdg-cache/go-build/8a/8a99fb3bb211ac63241740766134d6e88725cd54ab5009ad7d7db71b3efadc30-a b/.cell-installs/xdg-cache/go-build/8a/8a99fb3bb211ac63241740766134d6e88725cd54ab5009ad7d7db71b3efadc30-a
new file mode 100644
index 0000000..23bfa35
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8a/8a99fb3bb211ac63241740766134d6e88725cd54ab5009ad7d7db71b3efadc30-a
@@ -0,0 +1 @@
+v1 8a99fb3bb211ac63241740766134d6e88725cd54ab5009ad7d7db71b3efadc30 20f4ce001d9bd834c3a0d9417eb4f3ed462b37f22a0bb15464c96e5921b9a1ca                 2919  1787953153926343648
diff --git a/.cell-installs/xdg-cache/go-build/8a/8aac73b2530b08a9cdda9a7c643cdafcfc3c6939d095ecb56b5c609526bfb82c-a b/.cell-installs/xdg-cache/go-build/8a/8aac73b2530b08a9cdda9a7c643cdafcfc3c6939d095ecb56b5c609526bfb82c-a
new file mode 100644
index 0000000..e75c72e
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8a/8aac73b2530b08a9cdda9a7c643cdafcfc3c6939d095ecb56b5c609526bfb82c-a
@@ -0,0 +1 @@
+v1 8aac73b2530b08a9cdda9a7c643cdafcfc3c6939d095ecb56b5c609526bfb82c 39bd39fba732f09f0d9e114f063e979e0877d835f42dc2b074eaffb62e90670c                  513  1787953170160047724
diff --git a/.cell-installs/xdg-cache/go-build/8a/8ab2595afe90384e97f8698833b443296659ecdf4b45f8dd7ab6b6fe2eb73a8d-a b/.cell-installs/xdg-cache/go-build/8a/8ab2595afe90384e97f8698833b443296659ecdf4b45f8dd7ab6b6fe2eb73a8d-a
new file mode 100644
index 0000000..e2c965b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8a/8ab2595afe90384e97f8698833b443296659ecdf4b45f8dd7ab6b6fe2eb73a8d-a
@@ -0,0 +1 @@
+v1 8ab2595afe90384e97f8698833b443296659ecdf4b45f8dd7ab6b6fe2eb73a8d e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569355618896
diff --git a/.cell-installs/xdg-cache/go-build/8a/8ac1efddec180436a3b8dc707690b89d642783d3e82d8eb01a12092df0b27dad-a b/.cell-installs/xdg-cache/go-build/8a/8ac1efddec180436a3b8dc707690b89d642783d3e82d8eb01a12092df0b27dad-a
new file mode 100644
index 0000000..0e7a404
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8a/8ac1efddec180436a3b8dc707690b89d642783d3e82d8eb01a12092df0b27dad-a
@@ -0,0 +1 @@
+v1 8ac1efddec180436a3b8dc707690b89d642783d3e82d8eb01a12092df0b27dad e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570245750812
diff --git a/.cell-installs/xdg-cache/go-build/8b/8b12539a1ccd44b96fb94461dac39ae3c431cf4997067ccb4414ba522a064789-a b/.cell-installs/xdg-cache/go-build/8b/8b12539a1ccd44b96fb94461dac39ae3c431cf4997067ccb4414ba522a064789-a
new file mode 100644
index 0000000..8c8414c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8b/8b12539a1ccd44b96fb94461dac39ae3c431cf4997067ccb4414ba522a064789-a
@@ -0,0 +1 @@
+v1 8b12539a1ccd44b96fb94461dac39ae3c431cf4997067ccb4414ba522a064789 91c0984d4a4f0b1b8ccf4b09dbf8f411dabdb3fd88395ff5b5a4d3fac7c454c9                 2881  1787953170146595800
diff --git a/.cell-installs/xdg-cache/go-build/8b/8b4d00611bf193424d1121c4f40dfa86342aa6cfd1d4b3721c8d56d028f67ed6-a b/.cell-installs/xdg-cache/go-build/8b/8b4d00611bf193424d1121c4f40dfa86342aa6cfd1d4b3721c8d56d028f67ed6-a
new file mode 100644
index 0000000..c0ef55b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8b/8b4d00611bf193424d1121c4f40dfa86342aa6cfd1d4b3721c8d56d028f67ed6-a
@@ -0,0 +1 @@
+v1 8b4d00611bf193424d1121c4f40dfa86342aa6cfd1d4b3721c8d56d028f67ed6 a1a88da1b70076354fce6235e47ded63149a7d69ab24aace00e13b91219d23cc                 1225  1787953170144268911
diff --git a/.cell-installs/xdg-cache/go-build/8b/8b519498074d4fb47473b18969011ba1dc322013484341d1f2b88888ab8ba098-a b/.cell-installs/xdg-cache/go-build/8b/8b519498074d4fb47473b18969011ba1dc322013484341d1f2b88888ab8ba098-a
new file mode 100644
index 0000000..da1e75d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8b/8b519498074d4fb47473b18969011ba1dc322013484341d1f2b88888ab8ba098-a
@@ -0,0 +1 @@
+v1 8b519498074d4fb47473b18969011ba1dc322013484341d1f2b88888ab8ba098 8cc48a01f1cb9467edd3327f603416a255c02b1ad08ab72d11a1f80d2ea68e7e                 6552  1787953170159865161
diff --git a/.cell-installs/xdg-cache/go-build/8b/8bbdde8ea4e15fb53e7062744b99d44f20a5df8fac701edabde00a2c65071b39-a b/.cell-installs/xdg-cache/go-build/8b/8bbdde8ea4e15fb53e7062744b99d44f20a5df8fac701edabde00a2c65071b39-a
new file mode 100644
index 0000000..3eb0c4e
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8b/8bbdde8ea4e15fb53e7062744b99d44f20a5df8fac701edabde00a2c65071b39-a
@@ -0,0 +1 @@
+v1 8bbdde8ea4e15fb53e7062744b99d44f20a5df8fac701edabde00a2c65071b39 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569577475711
diff --git a/.cell-installs/xdg-cache/go-build/8c/8c1d90276b1ec004118b11bda6eb19c636fbbe0ea01873b143a334be4dcf4b5b-d b/.cell-installs/xdg-cache/go-build/8c/8c1d90276b1ec004118b11bda6eb19c636fbbe0ea01873b143a334be4dcf4b5b-d
new file mode 100644
index 0000000..5056bc2
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/8c/8c1d90276b1ec004118b11bda6eb19c636fbbe0ea01873b143a334be4dcf4b5b-d differ
diff --git a/.cell-installs/xdg-cache/go-build/8c/8c6b825005bfa80a2d79169762a983fd25052fad32dce448a3d9676321e17b43-a b/.cell-installs/xdg-cache/go-build/8c/8c6b825005bfa80a2d79169762a983fd25052fad32dce448a3d9676321e17b43-a
new file mode 100644
index 0000000..a5fc89e
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8c/8c6b825005bfa80a2d79169762a983fd25052fad32dce448a3d9676321e17b43-a
@@ -0,0 +1 @@
+v1 8c6b825005bfa80a2d79169762a983fd25052fad32dce448a3d9676321e17b43 5bc3176f5f663199617f39e2b43f0e31deb31fa3fdbf2cf7df700964c861438f                  260  1787953170152424068
diff --git a/.cell-installs/xdg-cache/go-build/8c/8c8fa5ad132483696928c890c5eb93b690a4449f562df346eefb54a7a9bc69be-d b/.cell-installs/xdg-cache/go-build/8c/8c8fa5ad132483696928c890c5eb93b690a4449f562df346eefb54a7a9bc69be-d
new file mode 100644
index 0000000..cd5a277
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/8c/8c8fa5ad132483696928c890c5eb93b690a4449f562df346eefb54a7a9bc69be-d differ
diff --git a/.cell-installs/xdg-cache/go-build/8c/8cc48a01f1cb9467edd3327f603416a255c02b1ad08ab72d11a1f80d2ea68e7e-d b/.cell-installs/xdg-cache/go-build/8c/8cc48a01f1cb9467edd3327f603416a255c02b1ad08ab72d11a1f80d2ea68e7e-d
new file mode 100644
index 0000000..487aa7a
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/8c/8cc48a01f1cb9467edd3327f603416a255c02b1ad08ab72d11a1f80d2ea68e7e-d differ
diff --git a/.cell-installs/xdg-cache/go-build/8c/8cc7b333d5ca7990be774b5eaf6497dca0301093c1d2e8bbd93de5ba1c14528c-d b/.cell-installs/xdg-cache/go-build/8c/8cc7b333d5ca7990be774b5eaf6497dca0301093c1d2e8bbd93de5ba1c14528c-d
new file mode 100644
index 0000000..6abdbdc
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/8c/8cc7b333d5ca7990be774b5eaf6497dca0301093c1d2e8bbd93de5ba1c14528c-d differ
diff --git a/.cell-installs/xdg-cache/go-build/8c/8ce0340b1f2d30c513b245fa8b51aa0378412f9e64f0d511a86d01ccb2498076-a b/.cell-installs/xdg-cache/go-build/8c/8ce0340b1f2d30c513b245fa8b51aa0378412f9e64f0d511a86d01ccb2498076-a
new file mode 100644
index 0000000..b319ec2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8c/8ce0340b1f2d30c513b245fa8b51aa0378412f9e64f0d511a86d01ccb2498076-a
@@ -0,0 +1 @@
+v1 8ce0340b1f2d30c513b245fa8b51aa0378412f9e64f0d511a86d01ccb2498076 17a678fa7e0d1624a6c02dd3ded8901328144219dbbc15abaf150fec4c173d6b                   49  1787953567783194705
diff --git a/.cell-installs/xdg-cache/go-build/8d/8d7bccc341adffc5f99102eb7b04123879112979330b6daade5669edb602fd2d-d b/.cell-installs/xdg-cache/go-build/8d/8d7bccc341adffc5f99102eb7b04123879112979330b6daade5669edb602fd2d-d
new file mode 100644
index 0000000..8b29057
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/8d/8d7bccc341adffc5f99102eb7b04123879112979330b6daade5669edb602fd2d-d differ
diff --git a/.cell-installs/xdg-cache/go-build/8d/8d83759066faeb339d266d3fcf076248111abddee88088b9477e6f23bcfeb90a-a b/.cell-installs/xdg-cache/go-build/8d/8d83759066faeb339d266d3fcf076248111abddee88088b9477e6f23bcfeb90a-a
new file mode 100644
index 0000000..dc57a22
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8d/8d83759066faeb339d266d3fcf076248111abddee88088b9477e6f23bcfeb90a-a
@@ -0,0 +1 @@
+v1 8d83759066faeb339d266d3fcf076248111abddee88088b9477e6f23bcfeb90a 28c97e51da30bea048e902dd6a0d6234e25468fd7de5f52ff19ba792e4bfcbac                 3374  1787953771568218996
diff --git a/.cell-installs/xdg-cache/go-build/8e/8e3f923846e440c54f0e0b0be1745b5ee7a3f20c0418a046224939fd860581b5-a b/.cell-installs/xdg-cache/go-build/8e/8e3f923846e440c54f0e0b0be1745b5ee7a3f20c0418a046224939fd860581b5-a
new file mode 100644
index 0000000..f766de2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8e/8e3f923846e440c54f0e0b0be1745b5ee7a3f20c0418a046224939fd860581b5-a
@@ -0,0 +1 @@
+v1 8e3f923846e440c54f0e0b0be1745b5ee7a3f20c0418a046224939fd860581b5 86adbbb15c53775a99f62697b7e04b4648ccd5ae09c2ebf3916c7f1aa915148c                  535  1787953294989964423
diff --git a/.cell-installs/xdg-cache/go-build/8e/8e9e7b7cc6a2194d4e2d1d83b289bf5347486db429dfc6fb5dee25de64bc9256-d b/.cell-installs/xdg-cache/go-build/8e/8e9e7b7cc6a2194d4e2d1d83b289bf5347486db429dfc6fb5dee25de64bc9256-d
new file mode 100644
index 0000000..2fe6ff5
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/8e/8e9e7b7cc6a2194d4e2d1d83b289bf5347486db429dfc6fb5dee25de64bc9256-d differ
diff --git a/.cell-installs/xdg-cache/go-build/8e/8eade61f42fa8a4bffb4b7944053b70c958ee2e1f8df86072ade7536166f9cb1-a b/.cell-installs/xdg-cache/go-build/8e/8eade61f42fa8a4bffb4b7944053b70c958ee2e1f8df86072ade7536166f9cb1-a
new file mode 100644
index 0000000..7fa8a5b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8e/8eade61f42fa8a4bffb4b7944053b70c958ee2e1f8df86072ade7536166f9cb1-a
@@ -0,0 +1 @@
+v1 8eade61f42fa8a4bffb4b7944053b70c958ee2e1f8df86072ade7536166f9cb1 c4cf441dd2d7d1f08c86ad4a2fb4ce560b78a676903b84d88caaa2270c183579                   23  1787953569309834930
diff --git a/.cell-installs/xdg-cache/go-build/8e/8ebc85e30c2df03429e32a441075a77dd64fcf8b23dbd0322e3b5b74c99df996-a b/.cell-installs/xdg-cache/go-build/8e/8ebc85e30c2df03429e32a441075a77dd64fcf8b23dbd0322e3b5b74c99df996-a
new file mode 100644
index 0000000..5d37be8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8e/8ebc85e30c2df03429e32a441075a77dd64fcf8b23dbd0322e3b5b74c99df996-a
@@ -0,0 +1 @@
+v1 8ebc85e30c2df03429e32a441075a77dd64fcf8b23dbd0322e3b5b74c99df996 b198c57fc35b1bb841034a322fb908796fce14c199b7034e871db883ee570f3d                   38  1787953567782444532
diff --git a/.cell-installs/xdg-cache/go-build/8e/8ebe879a33ce89e91adfc220224d8f9cb62d2eacb9aa7c2f3d45798a2820ad61-a b/.cell-installs/xdg-cache/go-build/8e/8ebe879a33ce89e91adfc220224d8f9cb62d2eacb9aa7c2f3d45798a2820ad61-a
new file mode 100644
index 0000000..1673c9b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8e/8ebe879a33ce89e91adfc220224d8f9cb62d2eacb9aa7c2f3d45798a2820ad61-a
@@ -0,0 +1 @@
+v1 8ebe879a33ce89e91adfc220224d8f9cb62d2eacb9aa7c2f3d45798a2820ad61 dac88fd70ad65a4a6560b4983838ac653e118b9d0903df9d5b1d1eceea808361                 1739  1787953153949350157
diff --git a/.cell-installs/xdg-cache/go-build/8f/8f56e5432ea265a7529b02459a3fb9ee4f0e460ca24e62679bf0b0ec5bb406a5-a b/.cell-installs/xdg-cache/go-build/8f/8f56e5432ea265a7529b02459a3fb9ee4f0e460ca24e62679bf0b0ec5bb406a5-a
new file mode 100644
index 0000000..bd2607b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8f/8f56e5432ea265a7529b02459a3fb9ee4f0e460ca24e62679bf0b0ec5bb406a5-a
@@ -0,0 +1 @@
+v1 8f56e5432ea265a7529b02459a3fb9ee4f0e460ca24e62679bf0b0ec5bb406a5 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569317607909
diff --git a/.cell-installs/xdg-cache/go-build/8f/8fb12eab410a3c0952b11306a33d23583254c968af5956a551839796156cd2d1-a b/.cell-installs/xdg-cache/go-build/8f/8fb12eab410a3c0952b11306a33d23583254c968af5956a551839796156cd2d1-a
new file mode 100644
index 0000000..01d04bf
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8f/8fb12eab410a3c0952b11306a33d23583254c968af5956a551839796156cd2d1-a
@@ -0,0 +1 @@
+v1 8fb12eab410a3c0952b11306a33d23583254c968af5956a551839796156cd2d1 49f23af4b354ee2b3fbed2f69f95aed9638c0f7adb14e65d2b17a75d95a0b0df               372146  1787953568936240486
diff --git a/.cell-installs/xdg-cache/go-build/8f/8ff0360e424bc4ee8567edb986347fe83b8c136a544fe7f664583702ba2a766c-a b/.cell-installs/xdg-cache/go-build/8f/8ff0360e424bc4ee8567edb986347fe83b8c136a544fe7f664583702ba2a766c-a
new file mode 100644
index 0000000..338bb48
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/8f/8ff0360e424bc4ee8567edb986347fe83b8c136a544fe7f664583702ba2a766c-a
@@ -0,0 +1 @@
+v1 8ff0360e424bc4ee8567edb986347fe83b8c136a544fe7f664583702ba2a766c cd5b49557d0254b87e3a6b8ea790363e8672a204d74c79f13e1b0d01e9694eed                  433  1787953170155737634
diff --git a/.cell-installs/xdg-cache/go-build/90/901a115bbb89bb5c3042c15bebc8ae38a3ab053486a8bface4a3aff532db432a-d b/.cell-installs/xdg-cache/go-build/90/901a115bbb89bb5c3042c15bebc8ae38a3ab053486a8bface4a3aff532db432a-d
new file mode 100644
index 0000000..45a7d56
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/90/901a115bbb89bb5c3042c15bebc8ae38a3ab053486a8bface4a3aff532db432a-d
@@ -0,0 +1,5 @@
+./casetables.go
+./digit.go
+./graphic.go
+./letter.go
+./tables.go
diff --git a/.cell-installs/xdg-cache/go-build/90/90536f033a75e0ee2707f1cc2c40816484d3a5236ca4c06b94c83ab887656494-a b/.cell-installs/xdg-cache/go-build/90/90536f033a75e0ee2707f1cc2c40816484d3a5236ca4c06b94c83ab887656494-a
new file mode 100644
index 0000000..898cbf3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/90/90536f033a75e0ee2707f1cc2c40816484d3a5236ca4c06b94c83ab887656494-a
@@ -0,0 +1 @@
+v1 90536f033a75e0ee2707f1cc2c40816484d3a5236ca4c06b94c83ab887656494 55ed99b88a68cf5492e921dd2d214c388b23d9aace0d7e0d525e7e4778482f90                   89  1787953568813243805
diff --git a/.cell-installs/xdg-cache/go-build/90/907649d4080f681bb0cab0eb567ed594714f7c1c8af51e21ba98b952ce5be620-a b/.cell-installs/xdg-cache/go-build/90/907649d4080f681bb0cab0eb567ed594714f7c1c8af51e21ba98b952ce5be620-a
new file mode 100644
index 0000000..07273ed
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/90/907649d4080f681bb0cab0eb567ed594714f7c1c8af51e21ba98b952ce5be620-a
@@ -0,0 +1 @@
+v1 907649d4080f681bb0cab0eb567ed594714f7c1c8af51e21ba98b952ce5be620 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569571743890
diff --git a/.cell-installs/xdg-cache/go-build/90/909826d643cee301438a1516c887595a2f72eb38bf8f8d1d55d8a27856fe3f59-a b/.cell-installs/xdg-cache/go-build/90/909826d643cee301438a1516c887595a2f72eb38bf8f8d1d55d8a27856fe3f59-a
new file mode 100644
index 0000000..956b478
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/90/909826d643cee301438a1516c887595a2f72eb38bf8f8d1d55d8a27856fe3f59-a
@@ -0,0 +1 @@
+v1 909826d643cee301438a1516c887595a2f72eb38bf8f8d1d55d8a27856fe3f59 8c1d90276b1ec004118b11bda6eb19c636fbbe0ea01873b143a334be4dcf4b5b                 1799  1787953153946718669
diff --git a/.cell-installs/xdg-cache/go-build/90/90997283dfba734ed2175b69ee73d102e029c6f8c67301d061b7bac00bc98501-a b/.cell-installs/xdg-cache/go-build/90/90997283dfba734ed2175b69ee73d102e029c6f8c67301d061b7bac00bc98501-a
new file mode 100644
index 0000000..ab2bdb8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/90/90997283dfba734ed2175b69ee73d102e029c6f8c67301d061b7bac00bc98501-a
@@ -0,0 +1 @@
+v1 90997283dfba734ed2175b69ee73d102e029c6f8c67301d061b7bac00bc98501 69bc9d9aab36a9b1b2c576399106bcac4c158bc13563cff9e4dc550d8bca7927              1105498  1787953567860084794
diff --git a/.cell-installs/xdg-cache/go-build/91/9126618cc63f77c5a5879b0b0dc04b6d33c20971766323efd57960207477b26e-a b/.cell-installs/xdg-cache/go-build/91/9126618cc63f77c5a5879b0b0dc04b6d33c20971766323efd57960207477b26e-a
new file mode 100644
index 0000000..83546ce
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/91/9126618cc63f77c5a5879b0b0dc04b6d33c20971766323efd57960207477b26e-a
@@ -0,0 +1 @@
+v1 9126618cc63f77c5a5879b0b0dc04b6d33c20971766323efd57960207477b26e e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567787507867
diff --git a/.cell-installs/xdg-cache/go-build/91/913b872653a2f7cb8dccac9a3bc863733908fae88a227f72506fb461aa5d8a19-d b/.cell-installs/xdg-cache/go-build/91/913b872653a2f7cb8dccac9a3bc863733908fae88a227f72506fb461aa5d8a19-d
new file mode 100644
index 0000000..e7b5ddc
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/91/913b872653a2f7cb8dccac9a3bc863733908fae88a227f72506fb461aa5d8a19-d differ
diff --git a/.cell-installs/xdg-cache/go-build/91/9158a5d9d6442aa12fdb3adf3cb106077aa3a24f7dbd6de70df331cb63b4ed5c-d b/.cell-installs/xdg-cache/go-build/91/9158a5d9d6442aa12fdb3adf3cb106077aa3a24f7dbd6de70df331cb63b4ed5c-d
new file mode 100644
index 0000000..176bc56
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/91/9158a5d9d6442aa12fdb3adf3cb106077aa3a24f7dbd6de70df331cb63b4ed5c-d
@@ -0,0 +1,10 @@
+./allocs.go
+./benchmark.go
+./cover.go
+./example.go
+./fuzz.go
+./match.go
+./newcover.go
+./run_example.go
+./testing.go
+./testing_other.go
diff --git a/.cell-installs/xdg-cache/go-build/91/91c0984d4a4f0b1b8ccf4b09dbf8f411dabdb3fd88395ff5b5a4d3fac7c454c9-d b/.cell-installs/xdg-cache/go-build/91/91c0984d4a4f0b1b8ccf4b09dbf8f411dabdb3fd88395ff5b5a4d3fac7c454c9-d
new file mode 100644
index 0000000..4b1a2c0
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/91/91c0984d4a4f0b1b8ccf4b09dbf8f411dabdb3fd88395ff5b5a4d3fac7c454c9-d differ
diff --git a/.cell-installs/xdg-cache/go-build/92/920f9a8f9cfa115de9e11866e63bc0e1152c933657aad70331d8c06c20c3bb17-a b/.cell-installs/xdg-cache/go-build/92/920f9a8f9cfa115de9e11866e63bc0e1152c933657aad70331d8c06c20c3bb17-a
new file mode 100644
index 0000000..88f0583
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/92/920f9a8f9cfa115de9e11866e63bc0e1152c933657aad70331d8c06c20c3bb17-a
@@ -0,0 +1 @@
+v1 920f9a8f9cfa115de9e11866e63bc0e1152c933657aad70331d8c06c20c3bb17 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569575270747
diff --git a/.cell-installs/xdg-cache/go-build/92/926e39d425046989453d60d7af2a2039771ccb7934f12935c6e89c1c8b69ce16-a b/.cell-installs/xdg-cache/go-build/92/926e39d425046989453d60d7af2a2039771ccb7934f12935c6e89c1c8b69ce16-a
new file mode 100644
index 0000000..3a81f82
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/92/926e39d425046989453d60d7af2a2039771ccb7934f12935c6e89c1c8b69ce16-a
@@ -0,0 +1 @@
+v1 926e39d425046989453d60d7af2a2039771ccb7934f12935c6e89c1c8b69ce16 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570194170222
diff --git a/.cell-installs/xdg-cache/go-build/92/927027a932615e25ed86387f9996f7e1a1bd53c18053a5a62ad1a84bffc8fe09-d b/.cell-installs/xdg-cache/go-build/92/927027a932615e25ed86387f9996f7e1a1bd53c18053a5a62ad1a84bffc8fe09-d
new file mode 100644
index 0000000..11b2bfb
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/92/927027a932615e25ed86387f9996f7e1a1bd53c18053a5a62ad1a84bffc8fe09-d differ
diff --git a/.cell-installs/xdg-cache/go-build/92/92f23655a833dacc46cc9be52d109fd8416e7be0123553ff00351cf7fc607f34-a b/.cell-installs/xdg-cache/go-build/92/92f23655a833dacc46cc9be52d109fd8416e7be0123553ff00351cf7fc607f34-a
new file mode 100644
index 0000000..d52bbee
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/92/92f23655a833dacc46cc9be52d109fd8416e7be0123553ff00351cf7fc607f34-a
@@ -0,0 +1 @@
+v1 92f23655a833dacc46cc9be52d109fd8416e7be0123553ff00351cf7fc607f34 3b0d5024b59175a57b2d6cd3cfde58e2bd3504d79addab57b7230d5363e628c6               241420  1787953569957108647
diff --git a/.cell-installs/xdg-cache/go-build/93/93c825a090695bf9bb01f310cda00a46211d75b6929f9c718f922eee352208e1-d b/.cell-installs/xdg-cache/go-build/93/93c825a090695bf9bb01f310cda00a46211d75b6929f9c718f922eee352208e1-d
new file mode 100644
index 0000000..16615dc
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/93/93c825a090695bf9bb01f310cda00a46211d75b6929f9c718f922eee352208e1-d differ
diff --git a/.cell-installs/xdg-cache/go-build/94/941433b8d5c4165dba2432452c39d0c6663336e32cba6e91d5d22116a088748e-a b/.cell-installs/xdg-cache/go-build/94/941433b8d5c4165dba2432452c39d0c6663336e32cba6e91d5d22116a088748e-a
new file mode 100644
index 0000000..91ecd56
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/94/941433b8d5c4165dba2432452c39d0c6663336e32cba6e91d5d22116a088748e-a
@@ -0,0 +1 @@
+v1 941433b8d5c4165dba2432452c39d0c6663336e32cba6e91d5d22116a088748e e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569305029881
diff --git a/.cell-installs/xdg-cache/go-build/94/9425e97d417a0f96d312414cf09a9637105bce01614cc9812cc657a913db1b1b-d b/.cell-installs/xdg-cache/go-build/94/9425e97d417a0f96d312414cf09a9637105bce01614cc9812cc657a913db1b1b-d
new file mode 100644
index 0000000..01cc084
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/94/9425e97d417a0f96d312414cf09a9637105bce01614cc9812cc657a913db1b1b-d differ
diff --git a/.cell-installs/xdg-cache/go-build/94/944a73f281b93b042dbc27a9fe8874eae6d3a844b9461b2bc89ac0d35bb930ca-a b/.cell-installs/xdg-cache/go-build/94/944a73f281b93b042dbc27a9fe8874eae6d3a844b9461b2bc89ac0d35bb930ca-a
new file mode 100644
index 0000000..8087488
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/94/944a73f281b93b042dbc27a9fe8874eae6d3a844b9461b2bc89ac0d35bb930ca-a
@@ -0,0 +1 @@
+v1 944a73f281b93b042dbc27a9fe8874eae6d3a844b9461b2bc89ac0d35bb930ca 343adbb0534750a39488ac9c7386212511d8b7e0cd714b953505f6cb858d22c6                 1586  1787953771567542604
diff --git a/.cell-installs/xdg-cache/go-build/94/945e4cbc3bc75bd99bcebe8f5c2b8ec115a9d0168fe8c71e8f420922b0594b4a-a b/.cell-installs/xdg-cache/go-build/94/945e4cbc3bc75bd99bcebe8f5c2b8ec115a9d0168fe8c71e8f420922b0594b4a-a
new file mode 100644
index 0000000..d15e7a0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/94/945e4cbc3bc75bd99bcebe8f5c2b8ec115a9d0168fe8c71e8f420922b0594b4a-a
@@ -0,0 +1 @@
+v1 945e4cbc3bc75bd99bcebe8f5c2b8ec115a9d0168fe8c71e8f420922b0594b4a 8675c40bae9c1de8423101e5c18feb8bd4914ac3453837aaf022b46af661290c                 2446  1787953170154659481
diff --git a/.cell-installs/xdg-cache/go-build/94/9477228b8c3a1ced716f1005811ecd22094c74b245571eb6220dffc4e9b6ef14-d b/.cell-installs/xdg-cache/go-build/94/9477228b8c3a1ced716f1005811ecd22094c74b245571eb6220dffc4e9b6ef14-d
new file mode 100644
index 0000000..603bc1f
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/94/9477228b8c3a1ced716f1005811ecd22094c74b245571eb6220dffc4e9b6ef14-d differ
diff --git a/.cell-installs/xdg-cache/go-build/95/950392ccc9df6f6c7875e9c7c8503b45c56c8e7e4905dddcf0025fca8a5eabe7-a b/.cell-installs/xdg-cache/go-build/95/950392ccc9df6f6c7875e9c7c8503b45c56c8e7e4905dddcf0025fca8a5eabe7-a
new file mode 100644
index 0000000..63e80a3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/95/950392ccc9df6f6c7875e9c7c8503b45c56c8e7e4905dddcf0025fca8a5eabe7-a
@@ -0,0 +1 @@
+v1 950392ccc9df6f6c7875e9c7c8503b45c56c8e7e4905dddcf0025fca8a5eabe7 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569575589016
diff --git a/.cell-installs/xdg-cache/go-build/95/952838e8dfa7e8fe8f1908376028275e0cd76022e77d3df6b18cc02e5999defa-d b/.cell-installs/xdg-cache/go-build/95/952838e8dfa7e8fe8f1908376028275e0cd76022e77d3df6b18cc02e5999defa-d
new file mode 100644
index 0000000..c7f57a7
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/95/952838e8dfa7e8fe8f1908376028275e0cd76022e77d3df6b18cc02e5999defa-d differ
diff --git a/.cell-installs/xdg-cache/go-build/95/955e4e1a715bc958121e1184f5b9c9456a936ff95bf433850edb5f269624c3d8-d b/.cell-installs/xdg-cache/go-build/95/955e4e1a715bc958121e1184f5b9c9456a936ff95bf433850edb5f269624c3d8-d
new file mode 100644
index 0000000..fa04af9
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/95/955e4e1a715bc958121e1184f5b9c9456a936ff95bf433850edb5f269624c3d8-d differ
diff --git a/.cell-installs/xdg-cache/go-build/95/95d49a012efaaddda40a5a003dd7691941aba50033bf7d6c5ff6a3315b890308-d b/.cell-installs/xdg-cache/go-build/95/95d49a012efaaddda40a5a003dd7691941aba50033bf7d6c5ff6a3315b890308-d
new file mode 100644
index 0000000..7da9ff8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/95/95d49a012efaaddda40a5a003dd7691941aba50033bf7d6c5ff6a3315b890308-d
@@ -0,0 +1,14 @@
+./atob.go
+./atoc.go
+./atof.go
+./atoi.go
+./bytealg.go
+./ctoa.go
+./decimal.go
+./doc.go
+./eisel_lemire.go
+./ftoa.go
+./ftoaryu.go
+./isprint.go
+./itoa.go
+./quote.go
diff --git a/.cell-installs/xdg-cache/go-build/96/963346a3c512f8c4ef1e4c2f20df20cb87f4e98534cd857413506334b6ed73ad-d b/.cell-installs/xdg-cache/go-build/96/963346a3c512f8c4ef1e4c2f20df20cb87f4e98534cd857413506334b6ed73ad-d
new file mode 100644
index 0000000..59e63cb
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/96/963346a3c512f8c4ef1e4c2f20df20cb87f4e98534cd857413506334b6ed73ad-d differ
diff --git a/.cell-installs/xdg-cache/go-build/96/967b66c7dffb1a99da52e5d0144f47fa462e023b0e995d547d3118ec79ec5081-a b/.cell-installs/xdg-cache/go-build/96/967b66c7dffb1a99da52e5d0144f47fa462e023b0e995d547d3118ec79ec5081-a
new file mode 100644
index 0000000..bf25da8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/96/967b66c7dffb1a99da52e5d0144f47fa462e023b0e995d547d3118ec79ec5081-a
@@ -0,0 +1 @@
+v1 967b66c7dffb1a99da52e5d0144f47fa462e023b0e995d547d3118ec79ec5081 7268825a631adbbde072cfbf30e0e8fc35078e90f1a38c9d4e53c206e2039f41                   22  1787953569991453179
diff --git a/.cell-installs/xdg-cache/go-build/96/969264d8c6c1ce564bc8e5866a55a4345573307052ca11cda1b1a28422ae1e3f-a b/.cell-installs/xdg-cache/go-build/96/969264d8c6c1ce564bc8e5866a55a4345573307052ca11cda1b1a28422ae1e3f-a
new file mode 100644
index 0000000..9bedfe1
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/96/969264d8c6c1ce564bc8e5866a55a4345573307052ca11cda1b1a28422ae1e3f-a
@@ -0,0 +1 @@
+v1 969264d8c6c1ce564bc8e5866a55a4345573307052ca11cda1b1a28422ae1e3f e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569700212343
diff --git a/.cell-installs/xdg-cache/go-build/96/96f0fa65bbf9208a5bb879cc17c4124997ae6c0da88574cf5860811f14fe955d-a b/.cell-installs/xdg-cache/go-build/96/96f0fa65bbf9208a5bb879cc17c4124997ae6c0da88574cf5860811f14fe955d-a
new file mode 100644
index 0000000..2e34eef
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/96/96f0fa65bbf9208a5bb879cc17c4124997ae6c0da88574cf5860811f14fe955d-a
@@ -0,0 +1 @@
+v1 96f0fa65bbf9208a5bb879cc17c4124997ae6c0da88574cf5860811f14fe955d e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568822225045
diff --git a/.cell-installs/xdg-cache/go-build/97/974e6cdd85e2ddf2f1a048df334d0ac30e178cccee3d7f4f0f4f84a000958742-d b/.cell-installs/xdg-cache/go-build/97/974e6cdd85e2ddf2f1a048df334d0ac30e178cccee3d7f4f0f4f84a000958742-d
new file mode 100644
index 0000000..61abee5
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/97/974e6cdd85e2ddf2f1a048df334d0ac30e178cccee3d7f4f0f4f84a000958742-d differ
diff --git a/.cell-installs/xdg-cache/go-build/97/975058930961b852e95688f378cb2a7da397b3a8064fa0d509f4f652a6290c2e-a b/.cell-installs/xdg-cache/go-build/97/975058930961b852e95688f378cb2a7da397b3a8064fa0d509f4f652a6290c2e-a
new file mode 100644
index 0000000..5c9c5f6
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/97/975058930961b852e95688f378cb2a7da397b3a8064fa0d509f4f652a6290c2e-a
@@ -0,0 +1 @@
+v1 975058930961b852e95688f378cb2a7da397b3a8064fa0d509f4f652a6290c2e 06b06f5d3ad757be70d3261c6ecd3f70745bd3ae269e73f742597ef7dfad5151               156914  1787953569910861559
diff --git a/.cell-installs/xdg-cache/go-build/98/9810499b716d1b7315351817efa3ccb51961d4c0b122c721c89f3b1b35c02f7e-a b/.cell-installs/xdg-cache/go-build/98/9810499b716d1b7315351817efa3ccb51961d4c0b122c721c89f3b1b35c02f7e-a
new file mode 100644
index 0000000..bb04ad8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/98/9810499b716d1b7315351817efa3ccb51961d4c0b122c721c89f3b1b35c02f7e-a
@@ -0,0 +1 @@
+v1 9810499b716d1b7315351817efa3ccb51961d4c0b122c721c89f3b1b35c02f7e e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570189231275
diff --git a/.cell-installs/xdg-cache/go-build/98/984ce46ce78c885b3365d96fd0ec596baffad21e09a30560b1e4d388139ae58f-a b/.cell-installs/xdg-cache/go-build/98/984ce46ce78c885b3365d96fd0ec596baffad21e09a30560b1e4d388139ae58f-a
new file mode 100644
index 0000000..f7b94ab
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/98/984ce46ce78c885b3365d96fd0ec596baffad21e09a30560b1e4d388139ae58f-a
@@ -0,0 +1 @@
+v1 984ce46ce78c885b3365d96fd0ec596baffad21e09a30560b1e4d388139ae58f b4f07cd8a0757cae0bc39355ea08c3674801eadcc225b1afdeed0f4dd7e92f82                   18  1787953567782439857
diff --git a/.cell-installs/xdg-cache/go-build/98/987426449d1a375ac18d83fe739c2f6325ae4917a74852a84e75ee25a38eacfc-d b/.cell-installs/xdg-cache/go-build/98/987426449d1a375ac18d83fe739c2f6325ae4917a74852a84e75ee25a38eacfc-d
new file mode 100644
index 0000000..848692d
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/98/987426449d1a375ac18d83fe739c2f6325ae4917a74852a84e75ee25a38eacfc-d differ
diff --git a/.cell-installs/xdg-cache/go-build/99/994e56643b89480a14bcbe93da2595e87c086b817ca2940ddde9c3139fdbf519-a b/.cell-installs/xdg-cache/go-build/99/994e56643b89480a14bcbe93da2595e87c086b817ca2940ddde9c3139fdbf519-a
new file mode 100644
index 0000000..337fe99
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/99/994e56643b89480a14bcbe93da2595e87c086b817ca2940ddde9c3139fdbf519-a
@@ -0,0 +1 @@
+v1 994e56643b89480a14bcbe93da2595e87c086b817ca2940ddde9c3139fdbf519 20bde6268b61bdad5fe936b7fbbabe8f7c02eaa95f82716c200849cc42d59fb7                 1628  1787953153934156093
diff --git a/.cell-installs/xdg-cache/go-build/99/999f31761566d23e19541354d554af7e40d71ea12f576f9715438503a13bd710-a b/.cell-installs/xdg-cache/go-build/99/999f31761566d23e19541354d554af7e40d71ea12f576f9715438503a13bd710-a
new file mode 100644
index 0000000..cf24bd3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/99/999f31761566d23e19541354d554af7e40d71ea12f576f9715438503a13bd710-a
@@ -0,0 +1 @@
+v1 999f31761566d23e19541354d554af7e40d71ea12f576f9715438503a13bd710 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569989208922
diff --git a/.cell-installs/xdg-cache/go-build/99/99ae9421d1b3b38f0c34a5302504b8d54dfef115ad1ce8c62ad93b99e3d1593a-a b/.cell-installs/xdg-cache/go-build/99/99ae9421d1b3b38f0c34a5302504b8d54dfef115ad1ce8c62ad93b99e3d1593a-a
new file mode 100644
index 0000000..22a7c2d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/99/99ae9421d1b3b38f0c34a5302504b8d54dfef115ad1ce8c62ad93b99e3d1593a-a
@@ -0,0 +1 @@
+v1 99ae9421d1b3b38f0c34a5302504b8d54dfef115ad1ce8c62ad93b99e3d1593a e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569647577599
diff --git a/.cell-installs/xdg-cache/go-build/99/99b82a49e34c309e21423998785d6f28cac365497d9f2d548cb5e15b52fe5cc7-a b/.cell-installs/xdg-cache/go-build/99/99b82a49e34c309e21423998785d6f28cac365497d9f2d548cb5e15b52fe5cc7-a
new file mode 100644
index 0000000..2b204f6
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/99/99b82a49e34c309e21423998785d6f28cac365497d9f2d548cb5e15b52fe5cc7-a
@@ -0,0 +1 @@
+v1 99b82a49e34c309e21423998785d6f28cac365497d9f2d548cb5e15b52fe5cc7 56e6a51653f2207ae2de540b8e72e47073c38247374fce78f7bc8be3f1f1b706                  199  1787953153932532007
diff --git a/.cell-installs/xdg-cache/go-build/99/99ca08d01295feb39e25f6580deebcccdec0e7c7ad4ec29d017c04f07faf097d-a b/.cell-installs/xdg-cache/go-build/99/99ca08d01295feb39e25f6580deebcccdec0e7c7ad4ec29d017c04f07faf097d-a
new file mode 100644
index 0000000..bf4438d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/99/99ca08d01295feb39e25f6580deebcccdec0e7c7ad4ec29d017c04f07faf097d-a
@@ -0,0 +1 @@
+v1 99ca08d01295feb39e25f6580deebcccdec0e7c7ad4ec29d017c04f07faf097d e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570185620539
diff --git a/.cell-installs/xdg-cache/go-build/9a/9a00f3fd29541d4de55f18a4f26b656cf3a6172415bf21973c0a98226f6b5dfb-d b/.cell-installs/xdg-cache/go-build/9a/9a00f3fd29541d4de55f18a4f26b656cf3a6172415bf21973c0a98226f6b5dfb-d
new file mode 100644
index 0000000..16e7fec
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/9a/9a00f3fd29541d4de55f18a4f26b656cf3a6172415bf21973c0a98226f6b5dfb-d differ
diff --git a/.cell-installs/xdg-cache/go-build/9a/9a1b3d29db1fccbe8d51aaef6988815a5491b96494d98f56f48dee9df303ef7f-a b/.cell-installs/xdg-cache/go-build/9a/9a1b3d29db1fccbe8d51aaef6988815a5491b96494d98f56f48dee9df303ef7f-a
new file mode 100644
index 0000000..30813ab
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/9a/9a1b3d29db1fccbe8d51aaef6988815a5491b96494d98f56f48dee9df303ef7f-a
@@ -0,0 +1 @@
+v1 9a1b3d29db1fccbe8d51aaef6988815a5491b96494d98f56f48dee9df303ef7f 5cd099f573ff613dadf03cea2d808962fe3df16bc4ab9b7b257e9052a2aa9264               292036  1787953569119150058
diff --git a/.cell-installs/xdg-cache/go-build/9a/9a548079f1151b7251d4813ff11defd0328abadd0b7f668c429ef8ba4ec2ed3d-a b/.cell-installs/xdg-cache/go-build/9a/9a548079f1151b7251d4813ff11defd0328abadd0b7f668c429ef8ba4ec2ed3d-a
new file mode 100644
index 0000000..11b0753
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/9a/9a548079f1151b7251d4813ff11defd0328abadd0b7f668c429ef8ba4ec2ed3d-a
@@ -0,0 +1 @@
+v1 9a548079f1151b7251d4813ff11defd0328abadd0b7f668c429ef8ba4ec2ed3d e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569091459244
diff --git a/.cell-installs/xdg-cache/go-build/9b/9b7f11015df0404c2160839a3f7ddba02e3ff847fc8f5f402f345a96b981b50f-a b/.cell-installs/xdg-cache/go-build/9b/9b7f11015df0404c2160839a3f7ddba02e3ff847fc8f5f402f345a96b981b50f-a
new file mode 100644
index 0000000..ddadc58
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/9b/9b7f11015df0404c2160839a3f7ddba02e3ff847fc8f5f402f345a96b981b50f-a
@@ -0,0 +1 @@
+v1 9b7f11015df0404c2160839a3f7ddba02e3ff847fc8f5f402f345a96b981b50f e9360993b5ed79d246b6e214268ef1803c5b7113b6f71b5c741cab881c66271e                  628  1787954345584970232
diff --git a/.cell-installs/xdg-cache/go-build/9b/9bca3364c8aa751d21aeafc3787472138207514c83a72ffe31a76223d3c80a1c-a b/.cell-installs/xdg-cache/go-build/9b/9bca3364c8aa751d21aeafc3787472138207514c83a72ffe31a76223d3c80a1c-a
new file mode 100644
index 0000000..38b1be3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/9b/9bca3364c8aa751d21aeafc3787472138207514c83a72ffe31a76223d3c80a1c-a
@@ -0,0 +1 @@
+v1 9bca3364c8aa751d21aeafc3787472138207514c83a72ffe31a76223d3c80a1c e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569593557136
diff --git a/.cell-installs/xdg-cache/go-build/9b/9bcd254cfe208ba823f2b3d6d5664eeee71a1d72730c69648a1ff4387b0f28ce-a b/.cell-installs/xdg-cache/go-build/9b/9bcd254cfe208ba823f2b3d6d5664eeee71a1d72730c69648a1ff4387b0f28ce-a
new file mode 100644
index 0000000..6cb5613
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/9b/9bcd254cfe208ba823f2b3d6d5664eeee71a1d72730c69648a1ff4387b0f28ce-a
@@ -0,0 +1 @@
+v1 9bcd254cfe208ba823f2b3d6d5664eeee71a1d72730c69648a1ff4387b0f28ce e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569316684544
diff --git a/.cell-installs/xdg-cache/go-build/9c/9c26cb03f7e021ecccec31c0a3b8882e5198433175d7cd5b90e9b74b00bac84d-a b/.cell-installs/xdg-cache/go-build/9c/9c26cb03f7e021ecccec31c0a3b8882e5198433175d7cd5b90e9b74b00bac84d-a
new file mode 100644
index 0000000..7192de8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/9c/9c26cb03f7e021ecccec31c0a3b8882e5198433175d7cd5b90e9b74b00bac84d-a
@@ -0,0 +1 @@
+v1 9c26cb03f7e021ecccec31c0a3b8882e5198433175d7cd5b90e9b74b00bac84d e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570186833667
diff --git a/.cell-installs/xdg-cache/go-build/9c/9cd1c3bf0072aa0dccb28141565da849924ff9255f955bac9d3587a5da754b0b-d b/.cell-installs/xdg-cache/go-build/9c/9cd1c3bf0072aa0dccb28141565da849924ff9255f955bac9d3587a5da754b0b-d
new file mode 100644
index 0000000..f97b880
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/9c/9cd1c3bf0072aa0dccb28141565da849924ff9255f955bac9d3587a5da754b0b-d
@@ -0,0 +1 @@
+./deps.go
diff --git a/.cell-installs/xdg-cache/go-build/9c/9cfcf1cdee2770fa9d5852db2342776d63182ac26ea6d5a519b56886ce6b6327-d b/.cell-installs/xdg-cache/go-build/9c/9cfcf1cdee2770fa9d5852db2342776d63182ac26ea6d5a519b56886ce6b6327-d
new file mode 100644
index 0000000..1c2601c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/9c/9cfcf1cdee2770fa9d5852db2342776d63182ac26ea6d5a519b56886ce6b6327-d differ
diff --git a/.cell-installs/xdg-cache/go-build/9d/9d08d11b97fdd1d31adad870590ecfa0604b7d4a0e9a35ae3d2077f3077dbb92-d b/.cell-installs/xdg-cache/go-build/9d/9d08d11b97fdd1d31adad870590ecfa0604b7d4a0e9a35ae3d2077f3077dbb92-d
new file mode 100644
index 0000000..fe0d8cb
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/9d/9d08d11b97fdd1d31adad870590ecfa0604b7d4a0e9a35ae3d2077f3077dbb92-d differ
diff --git a/.cell-installs/xdg-cache/go-build/9d/9d3626929d20259d1c1fa1ef82f890d285b9b2582e0427e7472a329c66db8b5b-d b/.cell-installs/xdg-cache/go-build/9d/9d3626929d20259d1c1fa1ef82f890d285b9b2582e0427e7472a329c66db8b5b-d
new file mode 100644
index 0000000..aaeb638
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/9d/9d3626929d20259d1c1fa1ef82f890d285b9b2582e0427e7472a329c66db8b5b-d differ
diff --git a/.cell-installs/xdg-cache/go-build/9d/9d48bbb86f9c5e5a881f4217ef37d11fd2d60f2d11d4b0ea8d5f04f8f6c7829a-a b/.cell-installs/xdg-cache/go-build/9d/9d48bbb86f9c5e5a881f4217ef37d11fd2d60f2d11d4b0ea8d5f04f8f6c7829a-a
new file mode 100644
index 0000000..2478d33
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/9d/9d48bbb86f9c5e5a881f4217ef37d11fd2d60f2d11d4b0ea8d5f04f8f6c7829a-a
@@ -0,0 +1 @@
+v1 9d48bbb86f9c5e5a881f4217ef37d11fd2d60f2d11d4b0ea8d5f04f8f6c7829a 9eb6294bc39979787b03eb7d39d5bf0cb5ae98f773ebcc790710c1d3e9773032                   25  1787953919151777324
diff --git a/.cell-installs/xdg-cache/go-build/9d/9d54c242a2539cab865d04793853f47bb35bd7d46935d80e9f86c06a1fd9551f-a b/.cell-installs/xdg-cache/go-build/9d/9d54c242a2539cab865d04793853f47bb35bd7d46935d80e9f86c06a1fd9551f-a
new file mode 100644
index 0000000..8a3149b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/9d/9d54c242a2539cab865d04793853f47bb35bd7d46935d80e9f86c06a1fd9551f-a
@@ -0,0 +1 @@
+v1 9d54c242a2539cab865d04793853f47bb35bd7d46935d80e9f86c06a1fd9551f e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570013492417
diff --git a/.cell-installs/xdg-cache/go-build/9d/9d955e4d9b8ada87370633c40a4c622c9ab6b05f56932cd7e4b1ef84418c61b2-a b/.cell-installs/xdg-cache/go-build/9d/9d955e4d9b8ada87370633c40a4c622c9ab6b05f56932cd7e4b1ef84418c61b2-a
new file mode 100644
index 0000000..ee8692a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/9d/9d955e4d9b8ada87370633c40a4c622c9ab6b05f56932cd7e4b1ef84418c61b2-a
@@ -0,0 +1 @@
+v1 9d955e4d9b8ada87370633c40a4c622c9ab6b05f56932cd7e4b1ef84418c61b2 fdaa17b4ff45e5c464f5ad4cfc664f0fc22ed2307650ac7eb00bd3a6409817b7                 2427  1787953771569345067
diff --git a/.cell-installs/xdg-cache/go-build/9d/9dbda35c4042bf5cc9685dc99baf39f8201faae252ea6c1ec517ebe186801318-d b/.cell-installs/xdg-cache/go-build/9d/9dbda35c4042bf5cc9685dc99baf39f8201faae252ea6c1ec517ebe186801318-d
new file mode 100644
index 0000000..814d0e6
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/9d/9dbda35c4042bf5cc9685dc99baf39f8201faae252ea6c1ec517ebe186801318-d differ
diff --git a/.cell-installs/xdg-cache/go-build/9e/9e14399bf06da03dba976621f2a5d6331d13903b0c1564a8c69f04a33feb59f5-d b/.cell-installs/xdg-cache/go-build/9e/9e14399bf06da03dba976621f2a5d6331d13903b0c1564a8c69f04a33feb59f5-d
new file mode 100644
index 0000000..9ec4aac
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/9e/9e14399bf06da03dba976621f2a5d6331d13903b0c1564a8c69f04a33feb59f5-d
@@ -0,0 +1 @@
+./encoding.go
diff --git a/.cell-installs/xdg-cache/go-build/9e/9e1dbb61ba300351417ef542f4b6bb405f09d36c211b98dad32171e22a1517a1-a b/.cell-installs/xdg-cache/go-build/9e/9e1dbb61ba300351417ef542f4b6bb405f09d36c211b98dad32171e22a1517a1-a
new file mode 100644
index 0000000..718c193
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/9e/9e1dbb61ba300351417ef542f4b6bb405f09d36c211b98dad32171e22a1517a1-a
@@ -0,0 +1 @@
+v1 9e1dbb61ba300351417ef542f4b6bb405f09d36c211b98dad32171e22a1517a1 1d7de0a4a37a85ba81db03d7946fbd3cc1d567abb07bc71a5334e34747dd997e               374626  1787953569119436303
diff --git a/.cell-installs/xdg-cache/go-build/9e/9e678f4a83be3e083e01f85eb15e600ff7f6a8094f4015fed39272ec5dfb7913-a b/.cell-installs/xdg-cache/go-build/9e/9e678f4a83be3e083e01f85eb15e600ff7f6a8094f4015fed39272ec5dfb7913-a
new file mode 100644
index 0000000..fd62fc7
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/9e/9e678f4a83be3e083e01f85eb15e600ff7f6a8094f4015fed39272ec5dfb7913-a
@@ -0,0 +1 @@
+v1 9e678f4a83be3e083e01f85eb15e600ff7f6a8094f4015fed39272ec5dfb7913 fbf683cd1314637c28aaf4fb65205d990c459938c32673d6492b0a046c5a2483                   12  1787953569879068247
diff --git a/.cell-installs/xdg-cache/go-build/9e/9eb6294bc39979787b03eb7d39d5bf0cb5ae98f773ebcc790710c1d3e9773032-d b/.cell-installs/xdg-cache/go-build/9e/9eb6294bc39979787b03eb7d39d5bf0cb5ae98f773ebcc790710c1d3e9773032-d
new file mode 100644
index 0000000..3708c17
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/9e/9eb6294bc39979787b03eb7d39d5bf0cb5ae98f773ebcc790710c1d3e9773032-d
@@ -0,0 +1,2 @@
+./cart.go
+./cart_test.go
diff --git a/.cell-installs/xdg-cache/go-build/9f/9f158a54822707f7bb2cdabff2f8db3872ec00364728b330fcb3332cabc823ba-d b/.cell-installs/xdg-cache/go-build/9f/9f158a54822707f7bb2cdabff2f8db3872ec00364728b330fcb3332cabc823ba-d
new file mode 100644
index 0000000..93b7104
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/9f/9f158a54822707f7bb2cdabff2f8db3872ec00364728b330fcb3332cabc823ba-d differ
diff --git a/.cell-installs/xdg-cache/go-build/9f/9f287ff6a562a9508214227756cd633abfb844b3324a412fbeb61e7ca92aa62c-a b/.cell-installs/xdg-cache/go-build/9f/9f287ff6a562a9508214227756cd633abfb844b3324a412fbeb61e7ca92aa62c-a
new file mode 100644
index 0000000..96408a4
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/9f/9f287ff6a562a9508214227756cd633abfb844b3324a412fbeb61e7ca92aa62c-a
@@ -0,0 +1 @@
+v1 9f287ff6a562a9508214227756cd633abfb844b3324a412fbeb61e7ca92aa62c d3f21047470b949bde25adaa11dec4f8bb3dad35cf0efe10be000340862891cb                   93  1787953569912275769
diff --git a/.cell-installs/xdg-cache/go-build/9f/9f5f2c2c50b41b8721dd1b53ba287892ef72a421639f9e6f909b7be7699a7230-d b/.cell-installs/xdg-cache/go-build/9f/9f5f2c2c50b41b8721dd1b53ba287892ef72a421639f9e6f909b7be7699a7230-d
new file mode 100644
index 0000000..3323ca5
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/9f/9f5f2c2c50b41b8721dd1b53ba287892ef72a421639f9e6f909b7be7699a7230-d differ
diff --git a/.cell-installs/xdg-cache/go-build/9f/9f8598cd5e49ae1255cbe91ab55a337b6a498f5ee285fd274b403560d8939f1d-a b/.cell-installs/xdg-cache/go-build/9f/9f8598cd5e49ae1255cbe91ab55a337b6a498f5ee285fd274b403560d8939f1d-a
new file mode 100644
index 0000000..cbcd4d3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/9f/9f8598cd5e49ae1255cbe91ab55a337b6a498f5ee285fd274b403560d8939f1d-a
@@ -0,0 +1 @@
+v1 9f8598cd5e49ae1255cbe91ab55a337b6a498f5ee285fd274b403560d8939f1d dbc59ae57a2a731a4f0fbd14f99972d0bbed46027ece4ee51c2a231b9c7bbe60                  473  1787953170165212294
diff --git a/.cell-installs/xdg-cache/go-build/9f/9feb76a30dfa0513489e2e742cca58556e46048e9785b3767c51315cfdb85af3-a b/.cell-installs/xdg-cache/go-build/9f/9feb76a30dfa0513489e2e742cca58556e46048e9785b3767c51315cfdb85af3-a
new file mode 100644
index 0000000..6c4b6b6
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/9f/9feb76a30dfa0513489e2e742cca58556e46048e9785b3767c51315cfdb85af3-a
@@ -0,0 +1 @@
+v1 9feb76a30dfa0513489e2e742cca58556e46048e9785b3767c51315cfdb85af3 0b47a1b62bbd2582c856a5fa62f0e91a2d89ca289dda1ba3074bc4783eea6555               108060  1787953154045862355
diff --git a/.cell-installs/xdg-cache/go-build/README b/.cell-installs/xdg-cache/go-build/README
new file mode 100644
index 0000000..a59d0c9
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/README
@@ -0,0 +1,4 @@
+This directory holds cached build artifacts from the Go build system.
+Run "go clean -cache" if the directory is getting too large.
+Run "go clean -fuzzcache" to delete the fuzz cache.
+See golang.org to learn more about Go.
diff --git a/.cell-installs/xdg-cache/go-build/a0/a0418e4d456e866b193ca536dff29d740d1e2fadf3097921aca8b1912367a110-a b/.cell-installs/xdg-cache/go-build/a0/a0418e4d456e866b193ca536dff29d740d1e2fadf3097921aca8b1912367a110-a
new file mode 100644
index 0000000..76187c1
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a0/a0418e4d456e866b193ca536dff29d740d1e2fadf3097921aca8b1912367a110-a
@@ -0,0 +1 @@
+v1 a0418e4d456e866b193ca536dff29d740d1e2fadf3097921aca8b1912367a110 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567811831378
diff --git a/.cell-installs/xdg-cache/go-build/a0/a05c139896a023363feea15b5613149202ee0d9060415fefc0306181bc3fb14e-a b/.cell-installs/xdg-cache/go-build/a0/a05c139896a023363feea15b5613149202ee0d9060415fefc0306181bc3fb14e-a
new file mode 100644
index 0000000..6721e2c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a0/a05c139896a023363feea15b5613149202ee0d9060415fefc0306181bc3fb14e-a
@@ -0,0 +1 @@
+v1 a05c139896a023363feea15b5613149202ee0d9060415fefc0306181bc3fb14e da36d38f5905f277e3dbbee5fb9807708592b3a65b8832865d3f45d9885a7b24                 2080  1787953771532768173
diff --git a/.cell-installs/xdg-cache/go-build/a0/a05f287fa8b4dda21e599f605dd0bf696ae51b11f7eb922c7a463988dd08cf3b-d b/.cell-installs/xdg-cache/go-build/a0/a05f287fa8b4dda21e599f605dd0bf696ae51b11f7eb922c7a463988dd08cf3b-d
new file mode 100644
index 0000000..74cf9b5
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a0/a05f287fa8b4dda21e599f605dd0bf696ae51b11f7eb922c7a463988dd08cf3b-d
@@ -0,0 +1,21 @@
+./copy_file_range_linux.go
+./errno_unix.go
+./fd.go
+./fd_fsync_posix.go
+./fd_mutex.go
+./fd_poll_runtime.go
+./fd_posix.go
+./fd_unix.go
+./fd_unixjs.go
+./fd_writev_unix.go
+./hook_cloexec.go
+./hook_unix.go
+./iovec_unix.go
+./sendfile_linux.go
+./sock_cloexec.go
+./sockopt.go
+./sockopt_linux.go
+./sockopt_unix.go
+./sockoptip.go
+./splice_linux.go
+./writev.go
diff --git a/.cell-installs/xdg-cache/go-build/a0/a07e525e78f00cc5e05f48e0e5b651b672a10e900ad2448ffc4009a6c0e83233-d b/.cell-installs/xdg-cache/go-build/a0/a07e525e78f00cc5e05f48e0e5b651b672a10e900ad2448ffc4009a6c0e83233-d
new file mode 100644
index 0000000..9b0ce91
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/a0/a07e525e78f00cc5e05f48e0e5b651b672a10e900ad2448ffc4009a6c0e83233-d differ
diff --git a/.cell-installs/xdg-cache/go-build/a0/a081422f09c698a34f06d03aa7162770640c6b09b55f5af1662148d896290ffb-d b/.cell-installs/xdg-cache/go-build/a0/a081422f09c698a34f06d03aa7162770640c6b09b55f5af1662148d896290ffb-d
new file mode 100644
index 0000000..05496c6
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/a0/a081422f09c698a34f06d03aa7162770640c6b09b55f5af1662148d896290ffb-d differ
diff --git a/.cell-installs/xdg-cache/go-build/a0/a08b58208fc00ff15c9eeca6fc9e8808a392ba74937c2a59e30d4784b3d14813-a b/.cell-installs/xdg-cache/go-build/a0/a08b58208fc00ff15c9eeca6fc9e8808a392ba74937c2a59e30d4784b3d14813-a
new file mode 100644
index 0000000..7ce52be
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a0/a08b58208fc00ff15c9eeca6fc9e8808a392ba74937c2a59e30d4784b3d14813-a
@@ -0,0 +1 @@
+v1 a08b58208fc00ff15c9eeca6fc9e8808a392ba74937c2a59e30d4784b3d14813 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570211245109
diff --git a/.cell-installs/xdg-cache/go-build/a0/a08f9aea6f6e965df32d71578e2bb8438ef15b7dac5e68ac91e3ea0061ce9b61-a b/.cell-installs/xdg-cache/go-build/a0/a08f9aea6f6e965df32d71578e2bb8438ef15b7dac5e68ac91e3ea0061ce9b61-a
new file mode 100644
index 0000000..b740544
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a0/a08f9aea6f6e965df32d71578e2bb8438ef15b7dac5e68ac91e3ea0061ce9b61-a
@@ -0,0 +1 @@
+v1 a08f9aea6f6e965df32d71578e2bb8438ef15b7dac5e68ac91e3ea0061ce9b61 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568983751164
diff --git a/.cell-installs/xdg-cache/go-build/a1/a12ec45d0ed13696815c748e1465279229d7aab127a478475bcce92b667ad210-a b/.cell-installs/xdg-cache/go-build/a1/a12ec45d0ed13696815c748e1465279229d7aab127a478475bcce92b667ad210-a
new file mode 100644
index 0000000..9efe87a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a1/a12ec45d0ed13696815c748e1465279229d7aab127a478475bcce92b667ad210-a
@@ -0,0 +1 @@
+v1 a12ec45d0ed13696815c748e1465279229d7aab127a478475bcce92b667ad210 1a218a0796c6449b4bb596c74afd9f5b224d814a37f1cfcc2cf32a1d423d0319                  129  1787953567789787416
diff --git a/.cell-installs/xdg-cache/go-build/a1/a18321082d5bf2de862d472cffcdd085298c2aa4a7d37fc1935714e1fb2edc19-d b/.cell-installs/xdg-cache/go-build/a1/a18321082d5bf2de862d472cffcdd085298c2aa4a7d37fc1935714e1fb2edc19-d
new file mode 100644
index 0000000..7cf9cfe
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/a1/a18321082d5bf2de862d472cffcdd085298c2aa4a7d37fc1935714e1fb2edc19-d differ
diff --git a/.cell-installs/xdg-cache/go-build/a1/a1a88da1b70076354fce6235e47ded63149a7d69ab24aace00e13b91219d23cc-d b/.cell-installs/xdg-cache/go-build/a1/a1a88da1b70076354fce6235e47ded63149a7d69ab24aace00e13b91219d23cc-d
new file mode 100644
index 0000000..397597f
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/a1/a1a88da1b70076354fce6235e47ded63149a7d69ab24aace00e13b91219d23cc-d differ
diff --git a/.cell-installs/xdg-cache/go-build/a1/a1b27a06dde351088cd231bbd80a6a8b250718636a86ebc5e8285f7171134a5f-d b/.cell-installs/xdg-cache/go-build/a1/a1b27a06dde351088cd231bbd80a6a8b250718636a86ebc5e8285f7171134a5f-d
new file mode 100644
index 0000000..85a6075
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/a1/a1b27a06dde351088cd231bbd80a6a8b250718636a86ebc5e8285f7171134a5f-d differ
diff --git a/.cell-installs/xdg-cache/go-build/a1/a1fa7d1d7d6df1fd0036aa80489f176556eedb29877a82fe04dc8bcaf897fcef-d b/.cell-installs/xdg-cache/go-build/a1/a1fa7d1d7d6df1fd0036aa80489f176556eedb29877a82fe04dc8bcaf897fcef-d
new file mode 100644
index 0000000..5cce697
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/a1/a1fa7d1d7d6df1fd0036aa80489f176556eedb29877a82fe04dc8bcaf897fcef-d differ
diff --git a/.cell-installs/xdg-cache/go-build/a2/a2a5ebc62255f10331547f98b4230afe03b32dc22fea8fc467ea6c2eaf59734a-a b/.cell-installs/xdg-cache/go-build/a2/a2a5ebc62255f10331547f98b4230afe03b32dc22fea8fc467ea6c2eaf59734a-a
new file mode 100644
index 0000000..a5ee93b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a2/a2a5ebc62255f10331547f98b4230afe03b32dc22fea8fc467ea6c2eaf59734a-a
@@ -0,0 +1 @@
+v1 a2a5ebc62255f10331547f98b4230afe03b32dc22fea8fc467ea6c2eaf59734a 79e345b89ac1ecaa0bb9bce77c06365f69ecc42eaa6ae78c7d833dc777f6fffb                   58  1787953567798232963
diff --git a/.cell-installs/xdg-cache/go-build/a3/a372522f243fd873de2f2515248be4024c2c1a7ddbfb27647b136d2dbc6b6634-d b/.cell-installs/xdg-cache/go-build/a3/a372522f243fd873de2f2515248be4024c2c1a7ddbfb27647b136d2dbc6b6634-d
new file mode 100644
index 0000000..b0ed568
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/a3/a372522f243fd873de2f2515248be4024c2c1a7ddbfb27647b136d2dbc6b6634-d differ
diff --git a/.cell-installs/xdg-cache/go-build/a3/a3c20a8cb4381cb74317cdaefa8715b2ca0f260c967663352f8a32f438d3dcbc-a b/.cell-installs/xdg-cache/go-build/a3/a3c20a8cb4381cb74317cdaefa8715b2ca0f260c967663352f8a32f438d3dcbc-a
new file mode 100644
index 0000000..3f06e6a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a3/a3c20a8cb4381cb74317cdaefa8715b2ca0f260c967663352f8a32f438d3dcbc-a
@@ -0,0 +1 @@
+v1 a3c20a8cb4381cb74317cdaefa8715b2ca0f260c967663352f8a32f438d3dcbc 48dcffd6203ee541a43fb13c5d947b744abd96043f264561e19caefe279967a8                   11  1787953569866927688
diff --git a/.cell-installs/xdg-cache/go-build/a3/a3ea2ddb288ddb803b0b50bd9045b6257eada13b6f5c5c9d7a84ef3e89c6a81d-d b/.cell-installs/xdg-cache/go-build/a3/a3ea2ddb288ddb803b0b50bd9045b6257eada13b6f5c5c9d7a84ef3e89c6a81d-d
new file mode 100644
index 0000000..b4f6187
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/a3/a3ea2ddb288ddb803b0b50bd9045b6257eada13b6f5c5c9d7a84ef3e89c6a81d-d differ
diff --git a/.cell-installs/xdg-cache/go-build/a4/a40ad51841d7450e47f5c0341080a69c59693a14d8c12819787cee496e4fe83f-a b/.cell-installs/xdg-cache/go-build/a4/a40ad51841d7450e47f5c0341080a69c59693a14d8c12819787cee496e4fe83f-a
new file mode 100644
index 0000000..d56a4a9
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a4/a40ad51841d7450e47f5c0341080a69c59693a14d8c12819787cee496e4fe83f-a
@@ -0,0 +1 @@
+v1 a40ad51841d7450e47f5c0341080a69c59693a14d8c12819787cee496e4fe83f e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569912764015
diff --git a/.cell-installs/xdg-cache/go-build/a4/a46209c72610b8c19afea6f3db163da6d44cd430f58800ba1377ed6ca2e62faf-d b/.cell-installs/xdg-cache/go-build/a4/a46209c72610b8c19afea6f3db163da6d44cd430f58800ba1377ed6ca2e62faf-d
new file mode 100644
index 0000000..19291d4
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/a4/a46209c72610b8c19afea6f3db163da6d44cd430f58800ba1377ed6ca2e62faf-d differ
diff --git a/.cell-installs/xdg-cache/go-build/a4/a469915137515d4d48455b4d98b87505dd5000c082e8bc355f378bbfb380a746-a b/.cell-installs/xdg-cache/go-build/a4/a469915137515d4d48455b4d98b87505dd5000c082e8bc355f378bbfb380a746-a
new file mode 100644
index 0000000..8e818c9
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a4/a469915137515d4d48455b4d98b87505dd5000c082e8bc355f378bbfb380a746-a
@@ -0,0 +1 @@
+v1 a469915137515d4d48455b4d98b87505dd5000c082e8bc355f378bbfb380a746 6f45513c26089e0787a30c9525bc03716b18622a2c2b5b77152631b33606c45c                  537  1787953567717265873
diff --git a/.cell-installs/xdg-cache/go-build/a4/a47a48d3f88ff29da754fadb02d446c81d68c07ce96e423f2638b48f6ec87f9c-a b/.cell-installs/xdg-cache/go-build/a4/a47a48d3f88ff29da754fadb02d446c81d68c07ce96e423f2638b48f6ec87f9c-a
new file mode 100644
index 0000000..9ebbeeb
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a4/a47a48d3f88ff29da754fadb02d446c81d68c07ce96e423f2638b48f6ec87f9c-a
@@ -0,0 +1 @@
+v1 a47a48d3f88ff29da754fadb02d446c81d68c07ce96e423f2638b48f6ec87f9c 95d49a012efaaddda40a5a003dd7691941aba50033bf7d6c5ff6a3315b890308                  160  1787953568823935668
diff --git a/.cell-installs/xdg-cache/go-build/a4/a4ba814269f5703704cd50196c5ff3cfde740235d4386863140506770a913283-a b/.cell-installs/xdg-cache/go-build/a4/a4ba814269f5703704cd50196c5ff3cfde740235d4386863140506770a913283-a
new file mode 100644
index 0000000..1b91c3f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a4/a4ba814269f5703704cd50196c5ff3cfde740235d4386863140506770a913283-a
@@ -0,0 +1 @@
+v1 a4ba814269f5703704cd50196c5ff3cfde740235d4386863140506770a913283 39201e26192f669f2c3aea560a5136daedf564b8c39a40f0e78413698fca4529                 2231  1787953170161813874
diff --git a/.cell-installs/xdg-cache/go-build/a4/a4e62c872181b607dd4fdbbb026fdedb0ba76d725fbe4ff3daea15adee93898a-d b/.cell-installs/xdg-cache/go-build/a4/a4e62c872181b607dd4fdbbb026fdedb0ba76d725fbe4ff3daea15adee93898a-d
new file mode 100644
index 0000000..4a928cf
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/a4/a4e62c872181b607dd4fdbbb026fdedb0ba76d725fbe4ff3daea15adee93898a-d differ
diff --git a/.cell-installs/xdg-cache/go-build/a5/a5106f501cb363b2bb9646d20000ff523c0cfc4b4b99bd5090c96698a63d2d88-a b/.cell-installs/xdg-cache/go-build/a5/a5106f501cb363b2bb9646d20000ff523c0cfc4b4b99bd5090c96698a63d2d88-a
new file mode 100644
index 0000000..c389039
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a5/a5106f501cb363b2bb9646d20000ff523c0cfc4b4b99bd5090c96698a63d2d88-a
@@ -0,0 +1 @@
+v1 a5106f501cb363b2bb9646d20000ff523c0cfc4b4b99bd5090c96698a63d2d88 76cbb554d5e9be4566f51998552c9ec85826ee78dc2277b742715c8227615fff               159756  1787953569943595856
diff --git a/.cell-installs/xdg-cache/go-build/a5/a53125637e13a3f2aadf35b223715541ce095b29a5474f83215e3d152bc792ff-a b/.cell-installs/xdg-cache/go-build/a5/a53125637e13a3f2aadf35b223715541ce095b29a5474f83215e3d152bc792ff-a
new file mode 100644
index 0000000..c4d4278
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a5/a53125637e13a3f2aadf35b223715541ce095b29a5474f83215e3d152bc792ff-a
@@ -0,0 +1 @@
+v1 a53125637e13a3f2aadf35b223715541ce095b29a5474f83215e3d152bc792ff 80cb8158f655f33ebfe81a7915cd40e591873a7efad630685e3b1f5439268c19                   13  1787953569094175187
diff --git a/.cell-installs/xdg-cache/go-build/a5/a54f954a3a3426c2d6fc028de2240317a75d3225123b7a1092633473856caff8-a b/.cell-installs/xdg-cache/go-build/a5/a54f954a3a3426c2d6fc028de2240317a75d3225123b7a1092633473856caff8-a
new file mode 100644
index 0000000..3d0f970
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a5/a54f954a3a3426c2d6fc028de2240317a75d3225123b7a1092633473856caff8-a
@@ -0,0 +1 @@
+v1 a54f954a3a3426c2d6fc028de2240317a75d3225123b7a1092633473856caff8 c57be060ec648dd4a30517536339520007a04ce752b67b40b55f54a1a7df76b5                   10  1787953567785272799
diff --git a/.cell-installs/xdg-cache/go-build/a5/a56f42ed1b9946009c32a29ceedf8d8c05b2012167d7acc5eabcfca78d7c627d-a b/.cell-installs/xdg-cache/go-build/a5/a56f42ed1b9946009c32a29ceedf8d8c05b2012167d7acc5eabcfca78d7c627d-a
new file mode 100644
index 0000000..fa9187c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a5/a56f42ed1b9946009c32a29ceedf8d8c05b2012167d7acc5eabcfca78d7c627d-a
@@ -0,0 +1 @@
+v1 a56f42ed1b9946009c32a29ceedf8d8c05b2012167d7acc5eabcfca78d7c627d e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569356359786
diff --git a/.cell-installs/xdg-cache/go-build/a5/a59bd4bb06ef3411364b7824a1e439db36d728f210fb62f27dfaa20a0b5543f9-a b/.cell-installs/xdg-cache/go-build/a5/a59bd4bb06ef3411364b7824a1e439db36d728f210fb62f27dfaa20a0b5543f9-a
new file mode 100644
index 0000000..5118d66
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a5/a59bd4bb06ef3411364b7824a1e439db36d728f210fb62f27dfaa20a0b5543f9-a
@@ -0,0 +1 @@
+v1 a59bd4bb06ef3411364b7824a1e439db36d728f210fb62f27dfaa20a0b5543f9 9cfcf1cdee2770fa9d5852db2342776d63182ac26ea6d5a519b56886ce6b6327                  404  1787953771571143294
diff --git a/.cell-installs/xdg-cache/go-build/a6/a63095a81b090df76d7b70bd2118d645d92d380dd5126f40efe056cd2e7b68cb-a b/.cell-installs/xdg-cache/go-build/a6/a63095a81b090df76d7b70bd2118d645d92d380dd5126f40efe056cd2e7b68cb-a
new file mode 100644
index 0000000..def880a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a6/a63095a81b090df76d7b70bd2118d645d92d380dd5126f40efe056cd2e7b68cb-a
@@ -0,0 +1 @@
+v1 a63095a81b090df76d7b70bd2118d645d92d380dd5126f40efe056cd2e7b68cb 3ec496f7e72d60d66b2915f3cf8975bb94b79c4d57e08c3f65fedf46eb5d0339                  428  1787953170166345867
diff --git a/.cell-installs/xdg-cache/go-build/a6/a634d4fc589457eb6b84a32e327e18a482cb690c000536a8bc6bdfebd7fc69b3-d b/.cell-installs/xdg-cache/go-build/a6/a634d4fc589457eb6b84a32e327e18a482cb690c000536a8bc6bdfebd7fc69b3-d
new file mode 100644
index 0000000..39c5f67
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/a6/a634d4fc589457eb6b84a32e327e18a482cb690c000536a8bc6bdfebd7fc69b3-d differ
diff --git a/.cell-installs/xdg-cache/go-build/a6/a6383e938539c95b2b483749d88c5cad93c4230d33b8f025180ad8c50484613a-a b/.cell-installs/xdg-cache/go-build/a6/a6383e938539c95b2b483749d88c5cad93c4230d33b8f025180ad8c50484613a-a
new file mode 100644
index 0000000..0f130e3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a6/a6383e938539c95b2b483749d88c5cad93c4230d33b8f025180ad8c50484613a-a
@@ -0,0 +1 @@
+v1 a6383e938539c95b2b483749d88c5cad93c4230d33b8f025180ad8c50484613a e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569118445178
diff --git a/.cell-installs/xdg-cache/go-build/a6/a65f513e6a186ac963aad47cfb4e42df1c57dfbdc9c33bbbc0531f312f62745d-d b/.cell-installs/xdg-cache/go-build/a6/a65f513e6a186ac963aad47cfb4e42df1c57dfbdc9c33bbbc0531f312f62745d-d
new file mode 100644
index 0000000..d6dd8bb
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/a6/a65f513e6a186ac963aad47cfb4e42df1c57dfbdc9c33bbbc0531f312f62745d-d differ
diff --git a/.cell-installs/xdg-cache/go-build/a6/a691e68a46d82528957bac042a7a188a83c007b42bdfa90239cfd4c268eebc52-a b/.cell-installs/xdg-cache/go-build/a6/a691e68a46d82528957bac042a7a188a83c007b42bdfa90239cfd4c268eebc52-a
new file mode 100644
index 0000000..c4e61c4
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a6/a691e68a46d82528957bac042a7a188a83c007b42bdfa90239cfd4c268eebc52-a
@@ -0,0 +1 @@
+v1 a691e68a46d82528957bac042a7a188a83c007b42bdfa90239cfd4c268eebc52 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569963808197
diff --git a/.cell-installs/xdg-cache/go-build/a6/a6ff495bee2faf4db30f0c2fb18c2ef92859cdc91f9a7351486370fc4446a90e-a b/.cell-installs/xdg-cache/go-build/a6/a6ff495bee2faf4db30f0c2fb18c2ef92859cdc91f9a7351486370fc4446a90e-a
new file mode 100644
index 0000000..6ab2cc9
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a6/a6ff495bee2faf4db30f0c2fb18c2ef92859cdc91f9a7351486370fc4446a90e-a
@@ -0,0 +1 @@
+v1 a6ff495bee2faf4db30f0c2fb18c2ef92859cdc91f9a7351486370fc4446a90e 6af88457a00ec61fce8dd11428da5febd90bc90fe146fa8db42f9ba6e0b09226                 2501  1787953771572617610
diff --git a/.cell-installs/xdg-cache/go-build/a7/a763b83f1cd3f6914d5615c900e961b861f7166758c1a2bff76ce3624c5eae9e-a b/.cell-installs/xdg-cache/go-build/a7/a763b83f1cd3f6914d5615c900e961b861f7166758c1a2bff76ce3624c5eae9e-a
new file mode 100644
index 0000000..8c8c6ae
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a7/a763b83f1cd3f6914d5615c900e961b861f7166758c1a2bff76ce3624c5eae9e-a
@@ -0,0 +1 @@
+v1 a763b83f1cd3f6914d5615c900e961b861f7166758c1a2bff76ce3624c5eae9e 7eacbd0cb1ffeecc9171db8b35a492b8de4ba9038bbfb7f3e7b70555caec7e58                10668  1787953153972952520
diff --git a/.cell-installs/xdg-cache/go-build/a7/a784140605c1f2fa0d84e32bba5b4d1baeded52b1898e94766f8793b818fc995-d b/.cell-installs/xdg-cache/go-build/a7/a784140605c1f2fa0d84e32bba5b4d1baeded52b1898e94766f8793b818fc995-d
new file mode 100644
index 0000000..a2f3f78
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/a7/a784140605c1f2fa0d84e32bba5b4d1baeded52b1898e94766f8793b818fc995-d differ
diff --git a/.cell-installs/xdg-cache/go-build/a7/a796f5c6fca03ad227d378e6e7c9ed354d2bc55c92574a767b3679a74d8d2883-a b/.cell-installs/xdg-cache/go-build/a7/a796f5c6fca03ad227d378e6e7c9ed354d2bc55c92574a767b3679a74d8d2883-a
new file mode 100644
index 0000000..25e4205
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a7/a796f5c6fca03ad227d378e6e7c9ed354d2bc55c92574a767b3679a74d8d2883-a
@@ -0,0 +1 @@
+v1 a796f5c6fca03ad227d378e6e7c9ed354d2bc55c92574a767b3679a74d8d2883 0228e8c8f89db1a322d617e46969cef886b9a0ebea8b462907df092f9339a73c                  251  1787953153943070080
diff --git a/.cell-installs/xdg-cache/go-build/a7/a7e9b54009eefbea2afb83b1ae7cd2014e53dda24a0414b048177b090b5651ec-a b/.cell-installs/xdg-cache/go-build/a7/a7e9b54009eefbea2afb83b1ae7cd2014e53dda24a0414b048177b090b5651ec-a
new file mode 100644
index 0000000..f8b111c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a7/a7e9b54009eefbea2afb83b1ae7cd2014e53dda24a0414b048177b090b5651ec-a
@@ -0,0 +1 @@
+v1 a7e9b54009eefbea2afb83b1ae7cd2014e53dda24a0414b048177b090b5651ec e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567858078841
diff --git a/.cell-installs/xdg-cache/go-build/a8/a821ae4ea712a7efe167db137425915d430862b3e0f037401e3db537e59faadb-a b/.cell-installs/xdg-cache/go-build/a8/a821ae4ea712a7efe167db137425915d430862b3e0f037401e3db537e59faadb-a
new file mode 100644
index 0000000..e477ff6
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a8/a821ae4ea712a7efe167db137425915d430862b3e0f037401e3db537e59faadb-a
@@ -0,0 +1 @@
+v1 a821ae4ea712a7efe167db137425915d430862b3e0f037401e3db537e59faadb e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569916000538
diff --git a/.cell-installs/xdg-cache/go-build/a8/a84b2cf81fc0b1c30f567827f7f6a583abc2cb17c95ce2d0cb024e06630c7be1-a b/.cell-installs/xdg-cache/go-build/a8/a84b2cf81fc0b1c30f567827f7f6a583abc2cb17c95ce2d0cb024e06630c7be1-a
new file mode 100644
index 0000000..1a86000
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a8/a84b2cf81fc0b1c30f567827f7f6a583abc2cb17c95ce2d0cb024e06630c7be1-a
@@ -0,0 +1 @@
+v1 a84b2cf81fc0b1c30f567827f7f6a583abc2cb17c95ce2d0cb024e06630c7be1 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567796416948
diff --git a/.cell-installs/xdg-cache/go-build/a8/a8980058458adc26933415a4ab8d77ec49556ba2430ee6cb63f7d27d2dd1e098-d b/.cell-installs/xdg-cache/go-build/a8/a8980058458adc26933415a4ab8d77ec49556ba2430ee6cb63f7d27d2dd1e098-d
new file mode 100644
index 0000000..f1a0ec3
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/a8/a8980058458adc26933415a4ab8d77ec49556ba2430ee6cb63f7d27d2dd1e098-d differ
diff --git a/.cell-installs/xdg-cache/go-build/a8/a8ae18b845338f96fc5505dae0d1a4fc3ce570516f71a36e6b5402d7eac5cf72-a b/.cell-installs/xdg-cache/go-build/a8/a8ae18b845338f96fc5505dae0d1a4fc3ce570516f71a36e6b5402d7eac5cf72-a
new file mode 100644
index 0000000..2eb97d4
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a8/a8ae18b845338f96fc5505dae0d1a4fc3ce570516f71a36e6b5402d7eac5cf72-a
@@ -0,0 +1 @@
+v1 a8ae18b845338f96fc5505dae0d1a4fc3ce570516f71a36e6b5402d7eac5cf72 974e6cdd85e2ddf2f1a048df334d0ac30e178cccee3d7f4f0f4f84a000958742               715478  1787953570061171628
diff --git a/.cell-installs/xdg-cache/go-build/a8/a8fe7f19281d2a08d59ad09b4b5370df6716cc7789a2c1b142f263b670262d0d-a b/.cell-installs/xdg-cache/go-build/a8/a8fe7f19281d2a08d59ad09b4b5370df6716cc7789a2c1b142f263b670262d0d-a
new file mode 100644
index 0000000..9b7b37a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a8/a8fe7f19281d2a08d59ad09b4b5370df6716cc7789a2c1b142f263b670262d0d-a
@@ -0,0 +1 @@
+v1 a8fe7f19281d2a08d59ad09b4b5370df6716cc7789a2c1b142f263b670262d0d 4851cd1a6a2902eec82a2d44a74b7c9a22b858e41b55299c47291bf076d59c14                   56  1787953354451759858
diff --git a/.cell-installs/xdg-cache/go-build/a9/a93b564eb954b1c9f8769000c8ef8a9e9a1430de6a92ff3999868c34eac1f8cc-a b/.cell-installs/xdg-cache/go-build/a9/a93b564eb954b1c9f8769000c8ef8a9e9a1430de6a92ff3999868c34eac1f8cc-a
new file mode 100644
index 0000000..c08f1c1
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a9/a93b564eb954b1c9f8769000c8ef8a9e9a1430de6a92ff3999868c34eac1f8cc-a
@@ -0,0 +1 @@
+v1 a93b564eb954b1c9f8769000c8ef8a9e9a1430de6a92ff3999868c34eac1f8cc 40a4dbdea6ad55f7c0a1d3dc2e23ba9bb39c0f74be66c2ca48121cd0146c8bb5                  525  1787953569145521499
diff --git a/.cell-installs/xdg-cache/go-build/a9/a96c3f482bddb82ba088d27c3b2526ead9a3d2a41997834be6096bf14eebcc29-d b/.cell-installs/xdg-cache/go-build/a9/a96c3f482bddb82ba088d27c3b2526ead9a3d2a41997834be6096bf14eebcc29-d
new file mode 100644
index 0000000..4cdc1aa
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/a9/a96c3f482bddb82ba088d27c3b2526ead9a3d2a41997834be6096bf14eebcc29-d differ
diff --git a/.cell-installs/xdg-cache/go-build/a9/a97671b268b4330271a143aef262166cd873db2e783bd03ffd4be34f99841de0-a b/.cell-installs/xdg-cache/go-build/a9/a97671b268b4330271a143aef262166cd873db2e783bd03ffd4be34f99841de0-a
new file mode 100644
index 0000000..b969b3f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/a9/a97671b268b4330271a143aef262166cd873db2e783bd03ffd4be34f99841de0-a
@@ -0,0 +1 @@
+v1 a97671b268b4330271a143aef262166cd873db2e783bd03ffd4be34f99841de0 04b4509d27fd9c93eb33d9e8d80ff91f4a3bd31a7c7e2b9a77367d5c2f33aca8                  114  1787953569910360634
diff --git a/.cell-installs/xdg-cache/go-build/a9/a9d0dae4cf16a3f4b93849c7da3619266c89245db550694737c6fd4854c073aa-d b/.cell-installs/xdg-cache/go-build/a9/a9d0dae4cf16a3f4b93849c7da3619266c89245db550694737c6fd4854c073aa-d
new file mode 100644
index 0000000..fdf3bd7
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/a9/a9d0dae4cf16a3f4b93849c7da3619266c89245db550694737c6fd4854c073aa-d differ
diff --git a/.cell-installs/xdg-cache/go-build/aa/aa6e57c94a75846311c0759c02e2fb83f5934399e6b8f01e3399b40ab42f411a-a b/.cell-installs/xdg-cache/go-build/aa/aa6e57c94a75846311c0759c02e2fb83f5934399e6b8f01e3399b40ab42f411a-a
new file mode 100644
index 0000000..a216a36
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/aa/aa6e57c94a75846311c0759c02e2fb83f5934399e6b8f01e3399b40ab42f411a-a
@@ -0,0 +1 @@
+v1 aa6e57c94a75846311c0759c02e2fb83f5934399e6b8f01e3399b40ab42f411a 69a8a35487589134e88fae6e9944960fe39e95e6e490fe2cb639ab48aaa35094                   10  1787954086842227506
diff --git a/.cell-installs/xdg-cache/go-build/aa/aaaf863ad8f66e3e28d7c4ad25a42da64cdd92a8874d387dc7feb48da8dc5bbe-d b/.cell-installs/xdg-cache/go-build/aa/aaaf863ad8f66e3e28d7c4ad25a42da64cdd92a8874d387dc7feb48da8dc5bbe-d
new file mode 100644
index 0000000..aa8a2fe
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/aa/aaaf863ad8f66e3e28d7c4ad25a42da64cdd92a8874d387dc7feb48da8dc5bbe-d differ
diff --git a/.cell-installs/xdg-cache/go-build/aa/aadc54645c3dd1616610e7297b627868c861f87253e3f12b49f7f132917d38e4-a b/.cell-installs/xdg-cache/go-build/aa/aadc54645c3dd1616610e7297b627868c861f87253e3f12b49f7f132917d38e4-a
new file mode 100644
index 0000000..1fb9555
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/aa/aadc54645c3dd1616610e7297b627868c861f87253e3f12b49f7f132917d38e4-a
@@ -0,0 +1 @@
+v1 aadc54645c3dd1616610e7297b627868c861f87253e3f12b49f7f132917d38e4 85088353d860a3d2a6fbccb40cad2fc97991ee4c1c2759c8597e78be81e9b7ab                  621  1787953153940412820
diff --git a/.cell-installs/xdg-cache/go-build/aa/aaf0b9f42a8fe525d8aa06f99f6b9ba3b7f8042b6206eb3679ad9a1ffff1095b-a b/.cell-installs/xdg-cache/go-build/aa/aaf0b9f42a8fe525d8aa06f99f6b9ba3b7f8042b6206eb3679ad9a1ffff1095b-a
new file mode 100644
index 0000000..12617f3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/aa/aaf0b9f42a8fe525d8aa06f99f6b9ba3b7f8042b6206eb3679ad9a1ffff1095b-a
@@ -0,0 +1 @@
+v1 aaf0b9f42a8fe525d8aa06f99f6b9ba3b7f8042b6206eb3679ad9a1ffff1095b e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568838293540
diff --git a/.cell-installs/xdg-cache/go-build/ab/ab0f58cf35f72da4d8ab558cc55d55364b36bb8a1fb81b5e662633da3b165305-d b/.cell-installs/xdg-cache/go-build/ab/ab0f58cf35f72da4d8ab558cc55d55364b36bb8a1fb81b5e662633da3b165305-d
new file mode 100644
index 0000000..a49aeb7
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/ab/ab0f58cf35f72da4d8ab558cc55d55364b36bb8a1fb81b5e662633da3b165305-d differ
diff --git a/.cell-installs/xdg-cache/go-build/ab/ab41dd27d3679b2526eeaa540e9ebee843f2dbba3663870359927338091c3fd9-a b/.cell-installs/xdg-cache/go-build/ab/ab41dd27d3679b2526eeaa540e9ebee843f2dbba3663870359927338091c3fd9-a
new file mode 100644
index 0000000..8ab4d0b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ab/ab41dd27d3679b2526eeaa540e9ebee843f2dbba3663870359927338091c3fd9-a
@@ -0,0 +1 @@
+v1 ab41dd27d3679b2526eeaa540e9ebee843f2dbba3663870359927338091c3fd9 0c0d2406829b5192ef4513ac501de781ccf483eb95fb76bfc7b5674a7c1170eb                   10  1787953569876057089
diff --git a/.cell-installs/xdg-cache/go-build/ab/ab5da294596108e036ec280ab6ed7e31d315e50f4e14a438c27b7af45205e682-a b/.cell-installs/xdg-cache/go-build/ab/ab5da294596108e036ec280ab6ed7e31d315e50f4e14a438c27b7af45205e682-a
new file mode 100644
index 0000000..92bc558
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ab/ab5da294596108e036ec280ab6ed7e31d315e50f4e14a438c27b7af45205e682-a
@@ -0,0 +1 @@
+v1 ab5da294596108e036ec280ab6ed7e31d315e50f4e14a438c27b7af45205e682 42c7b9899336757c626a97b38b9e75e2a6c06315d12d8c7c478b7cc8e94e7305                  149  1787953919183634186
diff --git a/.cell-installs/xdg-cache/go-build/ab/ab6371f60317d3f14c0d2c1a657848b8e0879a4824bd1c2331bef8ae94a32b02-a b/.cell-installs/xdg-cache/go-build/ab/ab6371f60317d3f14c0d2c1a657848b8e0879a4824bd1c2331bef8ae94a32b02-a
new file mode 100644
index 0000000..acfb883
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ab/ab6371f60317d3f14c0d2c1a657848b8e0879a4824bd1c2331bef8ae94a32b02-a
@@ -0,0 +1 @@
+v1 ab6371f60317d3f14c0d2c1a657848b8e0879a4824bd1c2331bef8ae94a32b02 1e30696906e91943b18ee45ff68ff32c622880ff207e55f6191c8f2f3a17b220                11904  1787953771563061348
diff --git a/.cell-installs/xdg-cache/go-build/ab/ab7a7c43f2af3bf8f2152af5fce03bec5a7a430d744842dc3ea95636763a6fcd-d b/.cell-installs/xdg-cache/go-build/ab/ab7a7c43f2af3bf8f2152af5fce03bec5a7a430d744842dc3ea95636763a6fcd-d
new file mode 100644
index 0000000..79751d9
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/ab/ab7a7c43f2af3bf8f2152af5fce03bec5a7a430d744842dc3ea95636763a6fcd-d differ
diff --git a/.cell-installs/xdg-cache/go-build/ab/aba4bc8e2998de9a917a9be403c994ea5133e2fb2122dd1312a2f807c8af9d62-a b/.cell-installs/xdg-cache/go-build/ab/aba4bc8e2998de9a917a9be403c994ea5133e2fb2122dd1312a2f807c8af9d62-a
new file mode 100644
index 0000000..5f7f51d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ab/aba4bc8e2998de9a917a9be403c994ea5133e2fb2122dd1312a2f807c8af9d62-a
@@ -0,0 +1 @@
+v1 aba4bc8e2998de9a917a9be403c994ea5133e2fb2122dd1312a2f807c8af9d62 7ace44d1bb2fe529b781fb8ad48e54c03a5cafe5665ca8b8a31adef5f4a7dca0                  839  1787953771537553806
diff --git a/.cell-installs/xdg-cache/go-build/ab/aba686b2781ef440f0a4aa6596edf4101f70278204273009f4eedeee6a09cd85-a b/.cell-installs/xdg-cache/go-build/ab/aba686b2781ef440f0a4aa6596edf4101f70278204273009f4eedeee6a09cd85-a
new file mode 100644
index 0000000..a6d890f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ab/aba686b2781ef440f0a4aa6596edf4101f70278204273009f4eedeee6a09cd85-a
@@ -0,0 +1 @@
+v1 aba686b2781ef440f0a4aa6596edf4101f70278204273009f4eedeee6a09cd85 3ca9f3d86328521b7ebdb67d2b142e225314e20995659acbecd86973d5c5a06e                57578  1787953567829873235
diff --git a/.cell-installs/xdg-cache/go-build/ab/abf9b086954be97a8a7e7baf77f11366040bd28741499c6ce1d0f6c934be44d6-d b/.cell-installs/xdg-cache/go-build/ab/abf9b086954be97a8a7e7baf77f11366040bd28741499c6ce1d0f6c934be44d6-d
new file mode 100644
index 0000000..011ac07
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ab/abf9b086954be97a8a7e7baf77f11366040bd28741499c6ce1d0f6c934be44d6-d
@@ -0,0 +1,30 @@
+./asan0.go
+./dirent.go
+./endian_little.go
+./env_unix.go
+./exec_linux.go
+./exec_unix.go
+./flock_linux.go
+./forkpipe2.go
+./lsf_linux.go
+./msan0.go
+./net.go
+./netlink_linux.go
+./rlimit.go
+./rlimit_stub.go
+./setuidgid_linux.go
+./sockcmsg_linux.go
+./sockcmsg_unix.go
+./sockcmsg_unix_other.go
+./syscall.go
+./syscall_linux.go
+./syscall_linux_accept4.go
+./syscall_linux_amd64.go
+./syscall_unix.go
+./time_nofake.go
+./timestruct.go
+./zerrors_linux_amd64.go
+./zsyscall_linux_amd64.go
+./zsysnum_linux_amd64.go
+./ztypes_linux_amd64.go
+./asm_linux_amd64.s
diff --git a/.cell-installs/xdg-cache/go-build/ac/ac1492df1277cbeeb2205126c8b460c5a9ae2cf94eb0e15475b544bcb92531b0-a b/.cell-installs/xdg-cache/go-build/ac/ac1492df1277cbeeb2205126c8b460c5a9ae2cf94eb0e15475b544bcb92531b0-a
new file mode 100644
index 0000000..5256a09
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ac/ac1492df1277cbeeb2205126c8b460c5a9ae2cf94eb0e15475b544bcb92531b0-a
@@ -0,0 +1 @@
+v1 ac1492df1277cbeeb2205126c8b460c5a9ae2cf94eb0e15475b544bcb92531b0 de4ab6ee7434df1a596c7fad60148ddb9aace2d98461267a8bdd91679f7e7192                  496  1787953771540409373
diff --git a/.cell-installs/xdg-cache/go-build/ac/ac3475974d44dc543d54e2b69e5fc678936c3b10900101ca40c58e531ae50e1f-d b/.cell-installs/xdg-cache/go-build/ac/ac3475974d44dc543d54e2b69e5fc678936c3b10900101ca40c58e531ae50e1f-d
new file mode 100644
index 0000000..1adf616
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/ac/ac3475974d44dc543d54e2b69e5fc678936c3b10900101ca40c58e531ae50e1f-d differ
diff --git a/.cell-installs/xdg-cache/go-build/ac/acc4505e9587e9679db61b5f25d204bb07ace206991f9a104a96cf73005eb12a-d b/.cell-installs/xdg-cache/go-build/ac/acc4505e9587e9679db61b5f25d204bb07ace206991f9a104a96cf73005eb12a-d
new file mode 100644
index 0000000..c78e139
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/ac/acc4505e9587e9679db61b5f25d204bb07ace206991f9a104a96cf73005eb12a-d differ
diff --git a/.cell-installs/xdg-cache/go-build/ac/acd963d8d91be0481b501b59e723cc3c8b81c18d24599b64f8891bbdf17e50c8-a b/.cell-installs/xdg-cache/go-build/ac/acd963d8d91be0481b501b59e723cc3c8b81c18d24599b64f8891bbdf17e50c8-a
new file mode 100644
index 0000000..a30440c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ac/acd963d8d91be0481b501b59e723cc3c8b81c18d24599b64f8891bbdf17e50c8-a
@@ -0,0 +1 @@
+v1 acd963d8d91be0481b501b59e723cc3c8b81c18d24599b64f8891bbdf17e50c8 5923bd9107d5115c8eee7cc9fe59eeb153c6086049202346df5f640a706253d5                 5220  1787953170167572398
diff --git a/.cell-installs/xdg-cache/go-build/ad/ad7e83db2492903cbe40f2c1a2b5ea5a1d34f7e140782b9c94be697651679485-a b/.cell-installs/xdg-cache/go-build/ad/ad7e83db2492903cbe40f2c1a2b5ea5a1d34f7e140782b9c94be697651679485-a
new file mode 100644
index 0000000..a190c0a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ad/ad7e83db2492903cbe40f2c1a2b5ea5a1d34f7e140782b9c94be697651679485-a
@@ -0,0 +1 @@
+v1 ad7e83db2492903cbe40f2c1a2b5ea5a1d34f7e140782b9c94be697651679485 29b051b653a394836f379f6d79fca8395d130465de3003fbacf8d3cf9396f976                   32  1787953568813124139
diff --git a/.cell-installs/xdg-cache/go-build/ad/adb61f4f74d6f24f55c2da511b539047725cf5515ad6aa5f012ee57271ddc352-d b/.cell-installs/xdg-cache/go-build/ad/adb61f4f74d6f24f55c2da511b539047725cf5515ad6aa5f012ee57271ddc352-d
new file mode 100644
index 0000000..53f1a83
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/ad/adb61f4f74d6f24f55c2da511b539047725cf5515ad6aa5f012ee57271ddc352-d differ
diff --git a/.cell-installs/xdg-cache/go-build/ae/ae447828aa56d629c781aa1fb8974b5665641f7dd6192562860fe575fb4f79d7-d b/.cell-installs/xdg-cache/go-build/ae/ae447828aa56d629c781aa1fb8974b5665641f7dd6192562860fe575fb4f79d7-d
new file mode 100644
index 0000000..54dcc0c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/ae/ae447828aa56d629c781aa1fb8974b5665641f7dd6192562860fe575fb4f79d7-d differ
diff --git a/.cell-installs/xdg-cache/go-build/ae/ae4874ecacec1a04dbd9a78da0956ecbe1c2ac55ce90fae7d45f98a3612a810d-a b/.cell-installs/xdg-cache/go-build/ae/ae4874ecacec1a04dbd9a78da0956ecbe1c2ac55ce90fae7d45f98a3612a810d-a
new file mode 100644
index 0000000..3b2be27
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ae/ae4874ecacec1a04dbd9a78da0956ecbe1c2ac55ce90fae7d45f98a3612a810d-a
@@ -0,0 +1 @@
+v1 ae4874ecacec1a04dbd9a78da0956ecbe1c2ac55ce90fae7d45f98a3612a810d c4adc29e06f70de05f9aa082fa9af8ffe44289c789247ebdce1f54f20ce67c8e                  387  1787953170153847243
diff --git a/.cell-installs/xdg-cache/go-build/ae/ae9df42eead5cbb9c7a3beb57c593522f98b1306d1700d4b0ada80fcf837e891-a b/.cell-installs/xdg-cache/go-build/ae/ae9df42eead5cbb9c7a3beb57c593522f98b1306d1700d4b0ada80fcf837e891-a
new file mode 100644
index 0000000..e3d93c8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ae/ae9df42eead5cbb9c7a3beb57c593522f98b1306d1700d4b0ada80fcf837e891-a
@@ -0,0 +1 @@
+v1 ae9df42eead5cbb9c7a3beb57c593522f98b1306d1700d4b0ada80fcf837e891 087832261f11fa6e6fe4ec2160bd1580530b3ca62179bed9093beef47b6229f6                  147  1787953569599846194
diff --git a/.cell-installs/xdg-cache/go-build/ae/aedfb205c0bb730af484b88b0d06903cbbfe5d3734da2a968bd4c52637596f5b-d b/.cell-installs/xdg-cache/go-build/ae/aedfb205c0bb730af484b88b0d06903cbbfe5d3734da2a968bd4c52637596f5b-d
new file mode 100644
index 0000000..297d607
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/ae/aedfb205c0bb730af484b88b0d06903cbbfe5d3734da2a968bd4c52637596f5b-d differ
diff --git a/.cell-installs/xdg-cache/go-build/af/af152bfee26b46bf31dde24786aeee6eabddbe322eab86a58a8bab5fba784598-a b/.cell-installs/xdg-cache/go-build/af/af152bfee26b46bf31dde24786aeee6eabddbe322eab86a58a8bab5fba784598-a
new file mode 100644
index 0000000..defa5d5
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/af/af152bfee26b46bf31dde24786aeee6eabddbe322eab86a58a8bab5fba784598-a
@@ -0,0 +1 @@
+v1 af152bfee26b46bf31dde24786aeee6eabddbe322eab86a58a8bab5fba784598 2f52bbcad7f48f13b96bbb5c5b5b3b997123b92dbcb4337b47f141bf63ce56f9                   50  1787953569992339611
diff --git a/.cell-installs/xdg-cache/go-build/af/af436a0169d5503180cc7b52473138651814935f3471e4b80c2ef29ac72c1fef-a b/.cell-installs/xdg-cache/go-build/af/af436a0169d5503180cc7b52473138651814935f3471e4b80c2ef29ac72c1fef-a
new file mode 100644
index 0000000..fc5acc8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/af/af436a0169d5503180cc7b52473138651814935f3471e4b80c2ef29ac72c1fef-a
@@ -0,0 +1 @@
+v1 af436a0169d5503180cc7b52473138651814935f3471e4b80c2ef29ac72c1fef e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567876282892
diff --git a/.cell-installs/xdg-cache/go-build/af/af86ea9d79473c84ec23e9098848fe24c8cda3e32e635ef50d5537e3112adbd0-a b/.cell-installs/xdg-cache/go-build/af/af86ea9d79473c84ec23e9098848fe24c8cda3e32e635ef50d5537e3112adbd0-a
new file mode 100644
index 0000000..e279e56
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/af/af86ea9d79473c84ec23e9098848fe24c8cda3e32e635ef50d5537e3112adbd0-a
@@ -0,0 +1 @@
+v1 af86ea9d79473c84ec23e9098848fe24c8cda3e32e635ef50d5537e3112adbd0 88093e39301c0f1b6a9abfae26798b1a22bffd0b4c8ead28614883c7cb68c478                   27  1787953569307241344
diff --git a/.cell-installs/xdg-cache/go-build/af/aff484c9a58ef62db3324b00b26d549c3fbd4f49590103b305e2513b90c1897f-a b/.cell-installs/xdg-cache/go-build/af/aff484c9a58ef62db3324b00b26d549c3fbd4f49590103b305e2513b90c1897f-a
new file mode 100644
index 0000000..99ff22b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/af/aff484c9a58ef62db3324b00b26d549c3fbd4f49590103b305e2513b90c1897f-a
@@ -0,0 +1 @@
+v1 aff484c9a58ef62db3324b00b26d549c3fbd4f49590103b305e2513b90c1897f 21faa15c5febcadadca5225fffd0292072de38e138bf5fe2ff635cc6450d7c4e                   52  1787953567790013049
diff --git a/.cell-installs/xdg-cache/go-build/b0/b0045288d598f993773c5e70920001f76f20801080df0fbc3732c04529a4d624-a b/.cell-installs/xdg-cache/go-build/b0/b0045288d598f993773c5e70920001f76f20801080df0fbc3732c04529a4d624-a
new file mode 100644
index 0000000..e4071c7
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b0/b0045288d598f993773c5e70920001f76f20801080df0fbc3732c04529a4d624-a
@@ -0,0 +1 @@
+v1 b0045288d598f993773c5e70920001f76f20801080df0fbc3732c04529a4d624 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570255459930
diff --git a/.cell-installs/xdg-cache/go-build/b0/b0127412d5be02afd0f55aab5d25a045f5ca5402d80e7096d027c3865f3e0e6a-a b/.cell-installs/xdg-cache/go-build/b0/b0127412d5be02afd0f55aab5d25a045f5ca5402d80e7096d027c3865f3e0e6a-a
new file mode 100644
index 0000000..b6e5e41
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b0/b0127412d5be02afd0f55aab5d25a045f5ca5402d80e7096d027c3865f3e0e6a-a
@@ -0,0 +1 @@
+v1 b0127412d5be02afd0f55aab5d25a045f5ca5402d80e7096d027c3865f3e0e6a e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570296680591
diff --git a/.cell-installs/xdg-cache/go-build/b0/b01a5dbb90a7da0a59b39f3442bbba455cd182ff509ecdf8e2475f6135376acc-d b/.cell-installs/xdg-cache/go-build/b0/b01a5dbb90a7da0a59b39f3442bbba455cd182ff509ecdf8e2475f6135376acc-d
new file mode 100644
index 0000000..90d3e72
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b0/b01a5dbb90a7da0a59b39f3442bbba455cd182ff509ecdf8e2475f6135376acc-d
@@ -0,0 +1,13 @@
+./counters_supported.go
+./coverage.go
+./encoding.go
+./fuzz.go
+./mem.go
+./minimize.go
+./mutator.go
+./mutators_byteslice.go
+./pcg.go
+./queue.go
+./sys_posix.go
+./trace.go
+./worker.go
diff --git a/.cell-installs/xdg-cache/go-build/b0/b0381684c1464899b3b57f7fd9577ca11e41f820d60b5395d6799beddfaf1b40-a b/.cell-installs/xdg-cache/go-build/b0/b0381684c1464899b3b57f7fd9577ca11e41f820d60b5395d6799beddfaf1b40-a
new file mode 100644
index 0000000..a137b76
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b0/b0381684c1464899b3b57f7fd9577ca11e41f820d60b5395d6799beddfaf1b40-a
@@ -0,0 +1 @@
+v1 b0381684c1464899b3b57f7fd9577ca11e41f820d60b5395d6799beddfaf1b40 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570068338522
diff --git a/.cell-installs/xdg-cache/go-build/b0/b088bdd1c5e688df3a077b1fa632873474c6a09a7131704490ee93dd05700aad-a b/.cell-installs/xdg-cache/go-build/b0/b088bdd1c5e688df3a077b1fa632873474c6a09a7131704490ee93dd05700aad-a
new file mode 100644
index 0000000..bfe2e1a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b0/b088bdd1c5e688df3a077b1fa632873474c6a09a7131704490ee93dd05700aad-a
@@ -0,0 +1 @@
+v1 b088bdd1c5e688df3a077b1fa632873474c6a09a7131704490ee93dd05700aad e9360993b5ed79d246b6e214268ef1803c5b7113b6f71b5c741cab881c66271e                  628  1787954418338097271
diff --git a/.cell-installs/xdg-cache/go-build/b0/b0e12990fe0092614dc96f453b38d36e187e016bc774214fb185a43517eaf100-a b/.cell-installs/xdg-cache/go-build/b0/b0e12990fe0092614dc96f453b38d36e187e016bc774214fb185a43517eaf100-a
new file mode 100644
index 0000000..b47127c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b0/b0e12990fe0092614dc96f453b38d36e187e016bc774214fb185a43517eaf100-a
@@ -0,0 +1 @@
+v1 b0e12990fe0092614dc96f453b38d36e187e016bc774214fb185a43517eaf100 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569155377171
diff --git a/.cell-installs/xdg-cache/go-build/b1/b129c9f8ffec76b7122c70392dc21ce283e0a5f12cb46932fe8f176890b133d7-a b/.cell-installs/xdg-cache/go-build/b1/b129c9f8ffec76b7122c70392dc21ce283e0a5f12cb46932fe8f176890b133d7-a
new file mode 100644
index 0000000..d2f943e
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b1/b129c9f8ffec76b7122c70392dc21ce283e0a5f12cb46932fe8f176890b133d7-a
@@ -0,0 +1 @@
+v1 b129c9f8ffec76b7122c70392dc21ce283e0a5f12cb46932fe8f176890b133d7 6353f35744a0a14dd5d52025f0f930e695b70bf3786e005cb542e804521549b7                   35  1787953569489348064
diff --git a/.cell-installs/xdg-cache/go-build/b1/b130d991c9796b6be26975c2d639b849a906a53a2217f96f3a00fb6aa5e7da24-d b/.cell-installs/xdg-cache/go-build/b1/b130d991c9796b6be26975c2d639b849a906a53a2217f96f3a00fb6aa5e7da24-d
new file mode 100644
index 0000000..c6ff3fd
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/b1/b130d991c9796b6be26975c2d639b849a906a53a2217f96f3a00fb6aa5e7da24-d differ
diff --git a/.cell-installs/xdg-cache/go-build/b1/b198c57fc35b1bb841034a322fb908796fce14c199b7034e871db883ee570f3d-d b/.cell-installs/xdg-cache/go-build/b1/b198c57fc35b1bb841034a322fb908796fce14c199b7034e871db883ee570f3d-d
new file mode 100644
index 0000000..3a253ac
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b1/b198c57fc35b1bb841034a322fb908796fce14c199b7034e871db883ee570f3d-d
@@ -0,0 +1,4 @@
+./doc.go
+./type.go
+./value.go
+./asm.s
diff --git a/.cell-installs/xdg-cache/go-build/b1/b1d3c58f5f190936734b25a1303f603dc990246ec072bf1494eca4110b866b76-a b/.cell-installs/xdg-cache/go-build/b1/b1d3c58f5f190936734b25a1303f603dc990246ec072bf1494eca4110b866b76-a
new file mode 100644
index 0000000..30d0d83
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b1/b1d3c58f5f190936734b25a1303f603dc990246ec072bf1494eca4110b866b76-a
@@ -0,0 +1 @@
+v1 b1d3c58f5f190936734b25a1303f603dc990246ec072bf1494eca4110b866b76 c966d8fa9f16af621edc2d079251c83ec5f18501d22cd79aa30641a03befecd1                 2858  1787953771540409798
diff --git a/.cell-installs/xdg-cache/go-build/b2/b2074e26f0087866c32f19b3ca6c943acd38d0a7d6baaefaebd62daf78fafc5a-a b/.cell-installs/xdg-cache/go-build/b2/b2074e26f0087866c32f19b3ca6c943acd38d0a7d6baaefaebd62daf78fafc5a-a
new file mode 100644
index 0000000..29c8983
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b2/b2074e26f0087866c32f19b3ca6c943acd38d0a7d6baaefaebd62daf78fafc5a-a
@@ -0,0 +1 @@
+v1 b2074e26f0087866c32f19b3ca6c943acd38d0a7d6baaefaebd62daf78fafc5a 7edee121e00ad962998899746a6fe47c76bf217d95cf569e292285225d18ef91                  638  1787953771570749839
diff --git a/.cell-installs/xdg-cache/go-build/b3/b39f61723f52c23df9012bcad50d4a69cce6ac485267f2722b0e189ebd623b4b-a b/.cell-installs/xdg-cache/go-build/b3/b39f61723f52c23df9012bcad50d4a69cce6ac485267f2722b0e189ebd623b4b-a
new file mode 100644
index 0000000..b5f4cce
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b3/b39f61723f52c23df9012bcad50d4a69cce6ac485267f2722b0e189ebd623b4b-a
@@ -0,0 +1 @@
+v1 b39f61723f52c23df9012bcad50d4a69cce6ac485267f2722b0e189ebd623b4b e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570271704395
diff --git a/.cell-installs/xdg-cache/go-build/b3/b3bd5dcfa59e7d13ecf423d218406c256a77bf1db818dd9710a24b9c3cfd2687-a b/.cell-installs/xdg-cache/go-build/b3/b3bd5dcfa59e7d13ecf423d218406c256a77bf1db818dd9710a24b9c3cfd2687-a
new file mode 100644
index 0000000..15027f5
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b3/b3bd5dcfa59e7d13ecf423d218406c256a77bf1db818dd9710a24b9c3cfd2687-a
@@ -0,0 +1 @@
+v1 b3bd5dcfa59e7d13ecf423d218406c256a77bf1db818dd9710a24b9c3cfd2687 42fb2d9e37a305e0b111c0cd83685348de1a28db6a814dc8b547dd79b45751ed                   63  1787953569911359488
diff --git a/.cell-installs/xdg-cache/go-build/b3/b3fe3073c134931bf550c339da960858af5e5317b3978fcbd83c781fd262ac8d-d b/.cell-installs/xdg-cache/go-build/b3/b3fe3073c134931bf550c339da960858af5e5317b3978fcbd83c781fd262ac8d-d
new file mode 100644
index 0000000..6f3e438
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/b3/b3fe3073c134931bf550c339da960858af5e5317b3978fcbd83c781fd262ac8d-d differ
diff --git a/.cell-installs/xdg-cache/go-build/b4/b42366b107e5ba3d8c6b56dae6a6e97cadb2a6864de6a092783410fd96348916-a b/.cell-installs/xdg-cache/go-build/b4/b42366b107e5ba3d8c6b56dae6a6e97cadb2a6864de6a092783410fd96348916-a
new file mode 100644
index 0000000..396e208
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b4/b42366b107e5ba3d8c6b56dae6a6e97cadb2a6864de6a092783410fd96348916-a
@@ -0,0 +1 @@
+v1 b42366b107e5ba3d8c6b56dae6a6e97cadb2a6864de6a092783410fd96348916 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569913105289
diff --git a/.cell-installs/xdg-cache/go-build/b4/b4309e3a5f45c5cce874b846e553e5bb56fe2bd884148d1d9297617e952ee690-a b/.cell-installs/xdg-cache/go-build/b4/b4309e3a5f45c5cce874b846e553e5bb56fe2bd884148d1d9297617e952ee690-a
new file mode 100644
index 0000000..4c60e4c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b4/b4309e3a5f45c5cce874b846e553e5bb56fe2bd884148d1d9297617e952ee690-a
@@ -0,0 +1 @@
+v1 b4309e3a5f45c5cce874b846e553e5bb56fe2bd884148d1d9297617e952ee690 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569571015083
diff --git a/.cell-installs/xdg-cache/go-build/b4/b4467325b528f6825208f940e1954151642edee2e22d9e2a7b305099888cb2c7-a b/.cell-installs/xdg-cache/go-build/b4/b4467325b528f6825208f940e1954151642edee2e22d9e2a7b305099888cb2c7-a
new file mode 100644
index 0000000..2072cea
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b4/b4467325b528f6825208f940e1954151642edee2e22d9e2a7b305099888cb2c7-a
@@ -0,0 +1 @@
+v1 b4467325b528f6825208f940e1954151642edee2e22d9e2a7b305099888cb2c7 86adbbb15c53775a99f62697b7e04b4648ccd5ae09c2ebf3916c7f1aa915148c                  535  1787953153922054169
diff --git a/.cell-installs/xdg-cache/go-build/b4/b48741b8a15ceff088cd60a5c707ef3e374bb7f012069cc28576ed274969a53e-d b/.cell-installs/xdg-cache/go-build/b4/b48741b8a15ceff088cd60a5c707ef3e374bb7f012069cc28576ed274969a53e-d
new file mode 100644
index 0000000..5df01e6
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b4/b48741b8a15ceff088cd60a5c707ef3e374bb7f012069cc28576ed274969a53e-d
@@ -0,0 +1,4 @@
+./cpu.go
+./cpu_x86.go
+./cpu.s
+./cpu_x86.s
diff --git a/.cell-installs/xdg-cache/go-build/b4/b4f07cd8a0757cae0bc39355ea08c3674801eadcc225b1afdeed0f4dd7e92f82-d b/.cell-installs/xdg-cache/go-build/b4/b4f07cd8a0757cae0bc39355ea08c3674801eadcc225b1afdeed0f4dd7e92f82-d
new file mode 100644
index 0000000..12461c5
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b4/b4f07cd8a0757cae0bc39355ea08c3674801eadcc225b1afdeed0f4dd7e92f82-d
@@ -0,0 +1 @@
+./unsafeheader.go
diff --git a/.cell-installs/xdg-cache/go-build/b5/b59a11387f43558fadad23e3e6da38db086d4f0f56ab2984d6c0dd72a38955ba-a b/.cell-installs/xdg-cache/go-build/b5/b59a11387f43558fadad23e3e6da38db086d4f0f56ab2984d6c0dd72a38955ba-a
new file mode 100644
index 0000000..72d8b8b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b5/b59a11387f43558fadad23e3e6da38db086d4f0f56ab2984d6c0dd72a38955ba-a
@@ -0,0 +1 @@
+v1 b59a11387f43558fadad23e3e6da38db086d4f0f56ab2984d6c0dd72a38955ba e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569938376117
diff --git a/.cell-installs/xdg-cache/go-build/b5/b5bc52004771c06ad330d202035fa8e1571f1a3a4a04c902b889af0e689032e2-d b/.cell-installs/xdg-cache/go-build/b5/b5bc52004771c06ad330d202035fa8e1571f1a3a4a04c902b889af0e689032e2-d
new file mode 100644
index 0000000..d890d93
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/b5/b5bc52004771c06ad330d202035fa8e1571f1a3a4a04c902b889af0e689032e2-d differ
diff --git a/.cell-installs/xdg-cache/go-build/b5/b5ec1a9ffc1d10322385d974cdbc3f99ba576fe9dfcd23dd0c82d849b4e0838f-d b/.cell-installs/xdg-cache/go-build/b5/b5ec1a9ffc1d10322385d974cdbc3f99ba576fe9dfcd23dd0c82d849b4e0838f-d
new file mode 100644
index 0000000..04546b7
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/b5/b5ec1a9ffc1d10322385d974cdbc3f99ba576fe9dfcd23dd0c82d849b4e0838f-d differ
diff --git a/.cell-installs/xdg-cache/go-build/b6/b621e04701f5e0998625f75f6cc43713fbd24fe588b77ec3fcc77cc76fa2b4e6-a b/.cell-installs/xdg-cache/go-build/b6/b621e04701f5e0998625f75f6cc43713fbd24fe588b77ec3fcc77cc76fa2b4e6-a
new file mode 100644
index 0000000..88395f2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b6/b621e04701f5e0998625f75f6cc43713fbd24fe588b77ec3fcc77cc76fa2b4e6-a
@@ -0,0 +1 @@
+v1 b621e04701f5e0998625f75f6cc43713fbd24fe588b77ec3fcc77cc76fa2b4e6 86a6f813f73eaf51bd0e27fd38670ece8a78028f625f884dbb23cd6c7b959c28                 3085  1787953170156703761
diff --git a/.cell-installs/xdg-cache/go-build/b6/b6aef64e45a700f5934b67f37596cf761c4b447b6f96aa1c5e01e76e79618206-a b/.cell-installs/xdg-cache/go-build/b6/b6aef64e45a700f5934b67f37596cf761c4b447b6f96aa1c5e01e76e79618206-a
new file mode 100644
index 0000000..8d94fca
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b6/b6aef64e45a700f5934b67f37596cf761c4b447b6f96aa1c5e01e76e79618206-a
@@ -0,0 +1 @@
+v1 b6aef64e45a700f5934b67f37596cf761c4b447b6f96aa1c5e01e76e79618206 da3a93f4ddab420f19552e8fe8e82b66a02125a8f27cd8b0f9cb0a41e49f86cb                33292  1787953567797088579
diff --git a/.cell-installs/xdg-cache/go-build/b6/b6cef41ae7333442ba4eaaf997c886e7af00d9fd3a1540abee88cd327f23378b-d b/.cell-installs/xdg-cache/go-build/b6/b6cef41ae7333442ba4eaaf997c886e7af00d9fd3a1540abee88cd327f23378b-d
new file mode 100644
index 0000000..4be7eb5
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/b6/b6cef41ae7333442ba4eaaf997c886e7af00d9fd3a1540abee88cd327f23378b-d differ
diff --git a/.cell-installs/xdg-cache/go-build/b6/b6eb2546f1e2539f2a9c298012b43caf467b7a33b0cee66fdb53c6c488ea1a4a-d b/.cell-installs/xdg-cache/go-build/b6/b6eb2546f1e2539f2a9c298012b43caf467b7a33b0cee66fdb53c6c488ea1a4a-d
new file mode 100644
index 0000000..812b3c8
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/b6/b6eb2546f1e2539f2a9c298012b43caf467b7a33b0cee66fdb53c6c488ea1a4a-d differ
diff --git a/.cell-installs/xdg-cache/go-build/b7/b70d8d56a354a8adbc74334175f3120e57ee035fe6e9d650524e3d5448eec0ef-d b/.cell-installs/xdg-cache/go-build/b7/b70d8d56a354a8adbc74334175f3120e57ee035fe6e9d650524e3d5448eec0ef-d
new file mode 100644
index 0000000..c939324
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/b7/b70d8d56a354a8adbc74334175f3120e57ee035fe6e9d650524e3d5448eec0ef-d differ
diff --git a/.cell-installs/xdg-cache/go-build/b7/b7803596d61aa540738d6e8d072bb76576af347ae0e3c8aab5e5d8ccab8aac0c-a b/.cell-installs/xdg-cache/go-build/b7/b7803596d61aa540738d6e8d072bb76576af347ae0e3c8aab5e5d8ccab8aac0c-a
new file mode 100644
index 0000000..cf6dda2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b7/b7803596d61aa540738d6e8d072bb76576af347ae0e3c8aab5e5d8ccab8aac0c-a
@@ -0,0 +1 @@
+v1 b7803596d61aa540738d6e8d072bb76576af347ae0e3c8aab5e5d8ccab8aac0c 07abd86d01b5a778b567fc49a8a06d9f80d9db944134cbb72177a19955f4a5a6                   20  1787953569877067268
diff --git a/.cell-installs/xdg-cache/go-build/b7/b7bd3713e0bb26047d9d69b317202f0a5f9a14dbb722c18bd0a798c9be3366fd-d b/.cell-installs/xdg-cache/go-build/b7/b7bd3713e0bb26047d9d69b317202f0a5f9a14dbb722c18bd0a798c9be3366fd-d
new file mode 100644
index 0000000..9a6e77f
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/b7/b7bd3713e0bb26047d9d69b317202f0a5f9a14dbb722c18bd0a798c9be3366fd-d differ
diff --git a/.cell-installs/xdg-cache/go-build/b8/b81aa35f49e27dbdbcb61138d1bc08ed5802b04af715823a760c9caf292b2c21-a b/.cell-installs/xdg-cache/go-build/b8/b81aa35f49e27dbdbcb61138d1bc08ed5802b04af715823a760c9caf292b2c21-a
new file mode 100644
index 0000000..ea3acb3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b8/b81aa35f49e27dbdbcb61138d1bc08ed5802b04af715823a760c9caf292b2c21-a
@@ -0,0 +1 @@
+v1 b81aa35f49e27dbdbcb61138d1bc08ed5802b04af715823a760c9caf292b2c21 9a00f3fd29541d4de55f18a4f26b656cf3a6172415bf21973c0a98226f6b5dfb              1378626  1787953570071056356
diff --git a/.cell-installs/xdg-cache/go-build/b8/b8d504480e02314e2a6ef3962948b77edfe947ff87ce4937aacb71005024b9bc-a b/.cell-installs/xdg-cache/go-build/b8/b8d504480e02314e2a6ef3962948b77edfe947ff87ce4937aacb71005024b9bc-a
new file mode 100644
index 0000000..bca03c8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b8/b8d504480e02314e2a6ef3962948b77edfe947ff87ce4937aacb71005024b9bc-a
@@ -0,0 +1 @@
+v1 b8d504480e02314e2a6ef3962948b77edfe947ff87ce4937aacb71005024b9bc e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567787943684
diff --git a/.cell-installs/xdg-cache/go-build/b9/b9058eab1559da584de1ed679fc9dc3055ae49653ee25186b120874cf870017a-a b/.cell-installs/xdg-cache/go-build/b9/b9058eab1559da584de1ed679fc9dc3055ae49653ee25186b120874cf870017a-a
new file mode 100644
index 0000000..8e18e62
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b9/b9058eab1559da584de1ed679fc9dc3055ae49653ee25186b120874cf870017a-a
@@ -0,0 +1 @@
+v1 b9058eab1559da584de1ed679fc9dc3055ae49653ee25186b120874cf870017a e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569918692169
diff --git a/.cell-installs/xdg-cache/go-build/b9/b93a884c58ae61ce9e11eb01749ceebc20521f977a11bc38149e165167320577-a b/.cell-installs/xdg-cache/go-build/b9/b93a884c58ae61ce9e11eb01749ceebc20521f977a11bc38149e165167320577-a
new file mode 100644
index 0000000..677c58a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b9/b93a884c58ae61ce9e11eb01749ceebc20521f977a11bc38149e165167320577-a
@@ -0,0 +1 @@
+v1 b93a884c58ae61ce9e11eb01749ceebc20521f977a11bc38149e165167320577 229b0468e36fc3e217f478e7db00895266c046567c39176b4ebfc75ba5ce088c                  847  1787953153930806319
diff --git a/.cell-installs/xdg-cache/go-build/b9/b963b1200fe9d79d32733f73f6c1b23a016ec953543edfb8c8f1417fb6548cb6-a b/.cell-installs/xdg-cache/go-build/b9/b963b1200fe9d79d32733f73f6c1b23a016ec953543edfb8c8f1417fb6548cb6-a
new file mode 100644
index 0000000..68a3bc1
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b9/b963b1200fe9d79d32733f73f6c1b23a016ec953543edfb8c8f1417fb6548cb6-a
@@ -0,0 +1 @@
+v1 b963b1200fe9d79d32733f73f6c1b23a016ec953543edfb8c8f1417fb6548cb6 69be00dd0a9ea45be83ab1a9eb79a92389af9a549378ae700202e18ce1459fc5                 2203  1787953771575376428
diff --git a/.cell-installs/xdg-cache/go-build/b9/b96ccef0935b428a2abf82e2f727c71008e99f6a901c46c6e78c833a5431afab-a b/.cell-installs/xdg-cache/go-build/b9/b96ccef0935b428a2abf82e2f727c71008e99f6a901c46c6e78c833a5431afab-a
new file mode 100644
index 0000000..2fdfbee
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b9/b96ccef0935b428a2abf82e2f727c71008e99f6a901c46c6e78c833a5431afab-a
@@ -0,0 +1 @@
+v1 b96ccef0935b428a2abf82e2f727c71008e99f6a901c46c6e78c833a5431afab d5aaa3589d0dd0f52656e7e1b1954ff20ba87ada974c5858fa8e5e0fc830ac52                  950  1787953771566499899
diff --git a/.cell-installs/xdg-cache/go-build/b9/b98d0285f8f8d7416637770d72dd9247dcf90edbc2bbabe9793d0b4da8a6177e-a b/.cell-installs/xdg-cache/go-build/b9/b98d0285f8f8d7416637770d72dd9247dcf90edbc2bbabe9793d0b4da8a6177e-a
new file mode 100644
index 0000000..1a2f00f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b9/b98d0285f8f8d7416637770d72dd9247dcf90edbc2bbabe9793d0b4da8a6177e-a
@@ -0,0 +1 @@
+v1 b98d0285f8f8d7416637770d72dd9247dcf90edbc2bbabe9793d0b4da8a6177e e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569621960993
diff --git a/.cell-installs/xdg-cache/go-build/b9/b98df03e459649843a8878c0b51083a42ca4871ada2b63b305d4201037000eba-a b/.cell-installs/xdg-cache/go-build/b9/b98df03e459649843a8878c0b51083a42ca4871ada2b63b305d4201037000eba-a
new file mode 100644
index 0000000..6c9d1d0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b9/b98df03e459649843a8878c0b51083a42ca4871ada2b63b305d4201037000eba-a
@@ -0,0 +1 @@
+v1 b98df03e459649843a8878c0b51083a42ca4871ada2b63b305d4201037000eba 07021552933f670e590c610c9108692ed55f3ac31156c84bcb41d78357d0a3ae                  366  1787953170190988427
diff --git a/.cell-installs/xdg-cache/go-build/b9/b9bef1d8a1daa438b176695eb71e75c300b55eae9ff58a5d6899e3bd329f56d5-a b/.cell-installs/xdg-cache/go-build/b9/b9bef1d8a1daa438b176695eb71e75c300b55eae9ff58a5d6899e3bd329f56d5-a
new file mode 100644
index 0000000..a473ca3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/b9/b9bef1d8a1daa438b176695eb71e75c300b55eae9ff58a5d6899e3bd329f56d5-a
@@ -0,0 +1 @@
+v1 b9bef1d8a1daa438b176695eb71e75c300b55eae9ff58a5d6899e3bd329f56d5 93c825a090695bf9bb01f310cda00a46211d75b6929f9c718f922eee352208e1                  417  1787953170167494021
diff --git a/.cell-installs/xdg-cache/go-build/ba/ba212673e2b604266eb2fdd5aff0ee11c44fe9cb6af4271b27a079c9c86fe4f5-a b/.cell-installs/xdg-cache/go-build/ba/ba212673e2b604266eb2fdd5aff0ee11c44fe9cb6af4271b27a079c9c86fe4f5-a
new file mode 100644
index 0000000..193954a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ba/ba212673e2b604266eb2fdd5aff0ee11c44fe9cb6af4271b27a079c9c86fe4f5-a
@@ -0,0 +1 @@
+v1 ba212673e2b604266eb2fdd5aff0ee11c44fe9cb6af4271b27a079c9c86fe4f5 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569316379046
diff --git a/.cell-installs/xdg-cache/go-build/ba/ba2b3dd8f28cac2ba90dfbec883524204985ca68128b5656809ec90fd07f4de4-a b/.cell-installs/xdg-cache/go-build/ba/ba2b3dd8f28cac2ba90dfbec883524204985ca68128b5656809ec90fd07f4de4-a
new file mode 100644
index 0000000..40417ec
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ba/ba2b3dd8f28cac2ba90dfbec883524204985ca68128b5656809ec90fd07f4de4-a
@@ -0,0 +1 @@
+v1 ba2b3dd8f28cac2ba90dfbec883524204985ca68128b5656809ec90fd07f4de4 da8bce33118ec9e0a09b492630317f20de76f65f1a22bed4007d8eb0ee048990                  554  1787953153964112274
diff --git a/.cell-installs/xdg-cache/go-build/ba/babc2d126eb1a5d1c7d5336f0f4756cf7e4b725ea260a9183669740f39098304-a b/.cell-installs/xdg-cache/go-build/ba/babc2d126eb1a5d1c7d5336f0f4756cf7e4b725ea260a9183669740f39098304-a
new file mode 100644
index 0000000..65b52ee
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ba/babc2d126eb1a5d1c7d5336f0f4756cf7e4b725ea260a9183669740f39098304-a
@@ -0,0 +1 @@
+v1 babc2d126eb1a5d1c7d5336f0f4756cf7e4b725ea260a9183669740f39098304 86adbbb15c53775a99f62697b7e04b4648ccd5ae09c2ebf3916c7f1aa915148c                  535  1787953238329807453
diff --git a/.cell-installs/xdg-cache/go-build/ba/bacbb21c54883d7c2f145b7bdf3d54de607ef457ccc068046a58d08b484fba3b-a b/.cell-installs/xdg-cache/go-build/ba/bacbb21c54883d7c2f145b7bdf3d54de607ef457ccc068046a58d08b484fba3b-a
new file mode 100644
index 0000000..6adf8ce
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ba/bacbb21c54883d7c2f145b7bdf3d54de607ef457ccc068046a58d08b484fba3b-a
@@ -0,0 +1 @@
+v1 bacbb21c54883d7c2f145b7bdf3d54de607ef457ccc068046a58d08b484fba3b 0f680f68803a3caeaadbcca731acdceded5ff5744c2bb7e686a5bf5b3539746c                 2167  1787953771539715968
diff --git a/.cell-installs/xdg-cache/go-build/ba/bacfd324fb2ed0fc15c58f9e2869e4c978e252696ca682e6286d6c528b6bfc78-a b/.cell-installs/xdg-cache/go-build/ba/bacfd324fb2ed0fc15c58f9e2869e4c978e252696ca682e6286d6c528b6bfc78-a
new file mode 100644
index 0000000..c8ce54a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ba/bacfd324fb2ed0fc15c58f9e2869e4c978e252696ca682e6286d6c528b6bfc78-a
@@ -0,0 +1 @@
+v1 bacfd324fb2ed0fc15c58f9e2869e4c978e252696ca682e6286d6c528b6bfc78 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569912752882
diff --git a/.cell-installs/xdg-cache/go-build/bc/bc0213c21e48f877a9f5399cec35518623d7e908cb8d6f1ecb5055abfec40a40-d b/.cell-installs/xdg-cache/go-build/bc/bc0213c21e48f877a9f5399cec35518623d7e908cb8d6f1ecb5055abfec40a40-d
new file mode 100644
index 0000000..3f22b9e
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/bc/bc0213c21e48f877a9f5399cec35518623d7e908cb8d6f1ecb5055abfec40a40-d differ
diff --git a/.cell-installs/xdg-cache/go-build/bc/bc04c7c94ed7c9a8048408aa4cf1d1061c9bb57e7adfa83a39af8a3a9a82685e-a b/.cell-installs/xdg-cache/go-build/bc/bc04c7c94ed7c9a8048408aa4cf1d1061c9bb57e7adfa83a39af8a3a9a82685e-a
new file mode 100644
index 0000000..b534a5f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/bc/bc04c7c94ed7c9a8048408aa4cf1d1061c9bb57e7adfa83a39af8a3a9a82685e-a
@@ -0,0 +1 @@
+v1 bc04c7c94ed7c9a8048408aa4cf1d1061c9bb57e7adfa83a39af8a3a9a82685e 196bcb8298ec68e9fd730bcd530179198ad0bb5a00c940141fb400f951b3cdc8                  571  1787954248648990142
diff --git a/.cell-installs/xdg-cache/go-build/bc/bc4fca54afb3622d5bcbc62ba2d05f9ae120ec313926727067d1a852b702d4cb-a b/.cell-installs/xdg-cache/go-build/bc/bc4fca54afb3622d5bcbc62ba2d05f9ae120ec313926727067d1a852b702d4cb-a
new file mode 100644
index 0000000..70f948f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/bc/bc4fca54afb3622d5bcbc62ba2d05f9ae120ec313926727067d1a852b702d4cb-a
@@ -0,0 +1 @@
+v1 bc4fca54afb3622d5bcbc62ba2d05f9ae120ec313926727067d1a852b702d4cb e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569915112932
diff --git a/.cell-installs/xdg-cache/go-build/bd/bd31440aba755b3c279e4ab053b413a45614e4fa1a14e5233af5d611284d6cda-d b/.cell-installs/xdg-cache/go-build/bd/bd31440aba755b3c279e4ab053b413a45614e4fa1a14e5233af5d611284d6cda-d
new file mode 100644
index 0000000..6744e61
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/bd/bd31440aba755b3c279e4ab053b413a45614e4fa1a14e5233af5d611284d6cda-d differ
diff --git a/.cell-installs/xdg-cache/go-build/be/be80ce7b060af24b742092b14898158d6663136335c584992d6e0c52e895545d-d b/.cell-installs/xdg-cache/go-build/be/be80ce7b060af24b742092b14898158d6663136335c584992d6e0c52e895545d-d
new file mode 100644
index 0000000..a6f50a3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/be/be80ce7b060af24b742092b14898158d6663136335c584992d6e0c52e895545d-d
@@ -0,0 +1,23 @@
+./accuracy_string.go
+./arith.go
+./arith_amd64.go
+./arith_decl.go
+./decimal.go
+./doc.go
+./float.go
+./floatconv.go
+./floatmarsh.go
+./ftoa.go
+./int.go
+./intconv.go
+./intmarsh.go
+./nat.go
+./natconv.go
+./natdiv.go
+./prime.go
+./rat.go
+./ratconv.go
+./ratmarsh.go
+./roundingmode_string.go
+./sqrt.go
+./arith_amd64.s
diff --git a/.cell-installs/xdg-cache/go-build/be/beae2b7fefaabb5b678426bf5b7f0e020f6fd3760e2f7caf10b131df48797d73-a b/.cell-installs/xdg-cache/go-build/be/beae2b7fefaabb5b678426bf5b7f0e020f6fd3760e2f7caf10b131df48797d73-a
new file mode 100644
index 0000000..b5acc96
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/be/beae2b7fefaabb5b678426bf5b7f0e020f6fd3760e2f7caf10b131df48797d73-a
@@ -0,0 +1 @@
+v1 beae2b7fefaabb5b678426bf5b7f0e020f6fd3760e2f7caf10b131df48797d73 317534f8ea017922fa3dbda21dc4192b09ab8c5a48ad5631999702f18f5ceb54                   37  1787953567781904898
diff --git a/.cell-installs/xdg-cache/go-build/be/beef32386f7973c3eb2ab5cf8f1ac6cc55625b591614c9ea482ab472d8a2a42d-d b/.cell-installs/xdg-cache/go-build/be/beef32386f7973c3eb2ab5cf8f1ac6cc55625b591614c9ea482ab472d8a2a42d-d
new file mode 100644
index 0000000..a48a282
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/be/beef32386f7973c3eb2ab5cf8f1ac6cc55625b591614c9ea482ab472d8a2a42d-d
@@ -0,0 +1,5 @@
+./garbage.go
+./mod.go
+./stack.go
+./stubs.go
+./debug.s
diff --git a/.cell-installs/xdg-cache/go-build/bf/bf03044cba6f9374a04c3291b6ec70d6a33e7de8892c1b4a88e8cd194bd3c7a2-d b/.cell-installs/xdg-cache/go-build/bf/bf03044cba6f9374a04c3291b6ec70d6a33e7de8892c1b4a88e8cd194bd3c7a2-d
new file mode 100644
index 0000000..a9fabda
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/bf/bf03044cba6f9374a04c3291b6ec70d6a33e7de8892c1b4a88e8cd194bd3c7a2-d differ
diff --git a/.cell-installs/xdg-cache/go-build/bf/bf05ae4a32f496426c3cc0c400ff4aff1ebd7ee7ac36342cb08d6e3882f97f53-a b/.cell-installs/xdg-cache/go-build/bf/bf05ae4a32f496426c3cc0c400ff4aff1ebd7ee7ac36342cb08d6e3882f97f53-a
new file mode 100644
index 0000000..ad5a679
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/bf/bf05ae4a32f496426c3cc0c400ff4aff1ebd7ee7ac36342cb08d6e3882f97f53-a
@@ -0,0 +1 @@
+v1 bf05ae4a32f496426c3cc0c400ff4aff1ebd7ee7ac36342cb08d6e3882f97f53 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569871191029
diff --git a/.cell-installs/xdg-cache/go-build/bf/bf51ae08343dc40c3db503f273e704c290adcee3f05b8de71dad824acee0fdab-d b/.cell-installs/xdg-cache/go-build/bf/bf51ae08343dc40c3db503f273e704c290adcee3f05b8de71dad824acee0fdab-d
new file mode 100644
index 0000000..485fdd6
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/bf/bf51ae08343dc40c3db503f273e704c290adcee3f05b8de71dad824acee0fdab-d differ
diff --git a/.cell-installs/xdg-cache/go-build/bf/bffb199af559a714a42c8abac4470e1006b268a54c342fd8995d7d06fe8c25d5-a b/.cell-installs/xdg-cache/go-build/bf/bffb199af559a714a42c8abac4470e1006b268a54c342fd8995d7d06fe8c25d5-a
new file mode 100644
index 0000000..c749e02
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/bf/bffb199af559a714a42c8abac4470e1006b268a54c342fd8995d7d06fe8c25d5-a
@@ -0,0 +1 @@
+v1 bffb199af559a714a42c8abac4470e1006b268a54c342fd8995d7d06fe8c25d5 47ca5f743267f9ce20acca61d1cef5a2decb9ca3b17d19f59f01a590b70e8b5c                   10  1787953569113982921
diff --git a/.cell-installs/xdg-cache/go-build/c0/c006f6b98f8b8679d49ee133387aaf81c465084a63cdc9939d5febb2fe105429-d b/.cell-installs/xdg-cache/go-build/c0/c006f6b98f8b8679d49ee133387aaf81c465084a63cdc9939d5febb2fe105429-d
new file mode 100644
index 0000000..b537852
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c0/c006f6b98f8b8679d49ee133387aaf81c465084a63cdc9939d5febb2fe105429-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c0/c011c73317d4e50060ab83ad5ae061014f9b92ea3f27f116cd4e1926cd96bb2a-a b/.cell-installs/xdg-cache/go-build/c0/c011c73317d4e50060ab83ad5ae061014f9b92ea3f27f116cd4e1926cd96bb2a-a
new file mode 100644
index 0000000..e4cdf8c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c0/c011c73317d4e50060ab83ad5ae061014f9b92ea3f27f116cd4e1926cd96bb2a-a
@@ -0,0 +1 @@
+v1 c011c73317d4e50060ab83ad5ae061014f9b92ea3f27f116cd4e1926cd96bb2a 2119038a233c74f65352b3a8b648034e2ebda67e5fc360ae0de85485cbd78353                  737  1787953170149965983
diff --git a/.cell-installs/xdg-cache/go-build/c0/c083aad19d87b60b45c65f5f1838db7b675d285c801b87ae4f9d688d01b9e55e-a b/.cell-installs/xdg-cache/go-build/c0/c083aad19d87b60b45c65f5f1838db7b675d285c801b87ae4f9d688d01b9e55e-a
new file mode 100644
index 0000000..2d6e666
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c0/c083aad19d87b60b45c65f5f1838db7b675d285c801b87ae4f9d688d01b9e55e-a
@@ -0,0 +1 @@
+v1 c083aad19d87b60b45c65f5f1838db7b675d285c801b87ae4f9d688d01b9e55e 196bcb8298ec68e9fd730bcd530179198ad0bb5a00c940141fb400f951b3cdc8                  571  1787953771524672523
diff --git a/.cell-installs/xdg-cache/go-build/c0/c0860180957ff905d84d66fe6ff5893ed0c969c1efe37173d78d3203f35080d6-a b/.cell-installs/xdg-cache/go-build/c0/c0860180957ff905d84d66fe6ff5893ed0c969c1efe37173d78d3203f35080d6-a
new file mode 100644
index 0000000..cec8902
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c0/c0860180957ff905d84d66fe6ff5893ed0c969c1efe37173d78d3203f35080d6-a
@@ -0,0 +1 @@
+v1 c0860180957ff905d84d66fe6ff5893ed0c969c1efe37173d78d3203f35080d6 9e14399bf06da03dba976621f2a5d6331d13903b0c1564a8c69f04a33feb59f5                   14  1787953567781414187
diff --git a/.cell-installs/xdg-cache/go-build/c1/c11376e592d859f2eea7f536340079749db49876961047f12d617b7de8d62e34-a b/.cell-installs/xdg-cache/go-build/c1/c11376e592d859f2eea7f536340079749db49876961047f12d617b7de8d62e34-a
new file mode 100644
index 0000000..c4ae7a4
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c1/c11376e592d859f2eea7f536340079749db49876961047f12d617b7de8d62e34-a
@@ -0,0 +1 @@
+v1 c11376e592d859f2eea7f536340079749db49876961047f12d617b7de8d62e34 6f0d7cd7a0e2e4dc50752b89c23b048fc0d67cb571276b0554cce28a65e064d2                   79  1787953567790087791
diff --git a/.cell-installs/xdg-cache/go-build/c1/c13a2aa56001f94684ad3a08839bb0396725a477a486d658b74df7ba82a27341-a b/.cell-installs/xdg-cache/go-build/c1/c13a2aa56001f94684ad3a08839bb0396725a477a486d658b74df7ba82a27341-a
new file mode 100644
index 0000000..ee2f7a2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c1/c13a2aa56001f94684ad3a08839bb0396725a477a486d658b74df7ba82a27341-a
@@ -0,0 +1 @@
+v1 c13a2aa56001f94684ad3a08839bb0396725a477a486d658b74df7ba82a27341 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569487326965
diff --git a/.cell-installs/xdg-cache/go-build/c1/c148cbf02843912a54af486b92131548ebad2c8a23537e864beeb1ea675f074b-d b/.cell-installs/xdg-cache/go-build/c1/c148cbf02843912a54af486b92131548ebad2c8a23537e864beeb1ea675f074b-d
new file mode 100644
index 0000000..a61580d
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c1/c148cbf02843912a54af486b92131548ebad2c8a23537e864beeb1ea675f074b-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c1/c155a78f38ef2154d5d330f44ed0ce49182c5e6d3ff9cb1876182d5fd17f4eec-a b/.cell-installs/xdg-cache/go-build/c1/c155a78f38ef2154d5d330f44ed0ce49182c5e6d3ff9cb1876182d5fd17f4eec-a
new file mode 100644
index 0000000..8f0a51b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c1/c155a78f38ef2154d5d330f44ed0ce49182c5e6d3ff9cb1876182d5fd17f4eec-a
@@ -0,0 +1 @@
+v1 c155a78f38ef2154d5d330f44ed0ce49182c5e6d3ff9cb1876182d5fd17f4eec e9360993b5ed79d246b6e214268ef1803c5b7113b6f71b5c741cab881c66271e                  628  1787954285700240639
diff --git a/.cell-installs/xdg-cache/go-build/c1/c1f39a8be80ff71c36ef25b1536e5ddb2a5be820f070cea5e9b3483045eebe55-d b/.cell-installs/xdg-cache/go-build/c1/c1f39a8be80ff71c36ef25b1536e5ddb2a5be820f070cea5e9b3483045eebe55-d
new file mode 100644
index 0000000..e9f8753
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c1/c1f39a8be80ff71c36ef25b1536e5ddb2a5be820f070cea5e9b3483045eebe55-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c2/c218e9496ddbb13f1f5a5630d9c317494525202997da0b246a3d0565a1523e30-a b/.cell-installs/xdg-cache/go-build/c2/c218e9496ddbb13f1f5a5630d9c317494525202997da0b246a3d0565a1523e30-a
new file mode 100644
index 0000000..c603298
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c2/c218e9496ddbb13f1f5a5630d9c317494525202997da0b246a3d0565a1523e30-a
@@ -0,0 +1 @@
+v1 c218e9496ddbb13f1f5a5630d9c317494525202997da0b246a3d0565a1523e30 c38fedb481c0a89eb25cb996e08d9f4c75e6aad3cc76853e99a830bc7355d319                35708  1787953569244967297
diff --git a/.cell-installs/xdg-cache/go-build/c3/c30c7406e98f2b98b3e0d2e9bdad052573865dd01ac197bbf000000e00d4f781-d b/.cell-installs/xdg-cache/go-build/c3/c30c7406e98f2b98b3e0d2e9bdad052573865dd01ac197bbf000000e00d4f781-d
new file mode 100644
index 0000000..5fcf742
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c3/c30c7406e98f2b98b3e0d2e9bdad052573865dd01ac197bbf000000e00d4f781-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c3/c33d39baad75170fdde723be2e3432b923aa3c6e57b71aa2b20bb54a3e2864a5-d b/.cell-installs/xdg-cache/go-build/c3/c33d39baad75170fdde723be2e3432b923aa3c6e57b71aa2b20bb54a3e2864a5-d
new file mode 100644
index 0000000..7de2d77
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c3/c33d39baad75170fdde723be2e3432b923aa3c6e57b71aa2b20bb54a3e2864a5-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c3/c3424b9467c92fd572e5b79fa2baa0798bf9c0ae26e23ece759e05ef57cd5f9b-a b/.cell-installs/xdg-cache/go-build/c3/c3424b9467c92fd572e5b79fa2baa0798bf9c0ae26e23ece759e05ef57cd5f9b-a
new file mode 100644
index 0000000..b4c5876
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c3/c3424b9467c92fd572e5b79fa2baa0798bf9c0ae26e23ece759e05ef57cd5f9b-a
@@ -0,0 +1 @@
+v1 c3424b9467c92fd572e5b79fa2baa0798bf9c0ae26e23ece759e05ef57cd5f9b e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569641082322
diff --git a/.cell-installs/xdg-cache/go-build/c3/c38fedb481c0a89eb25cb996e08d9f4c75e6aad3cc76853e99a830bc7355d319-d b/.cell-installs/xdg-cache/go-build/c3/c38fedb481c0a89eb25cb996e08d9f4c75e6aad3cc76853e99a830bc7355d319-d
new file mode 100644
index 0000000..22babba
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c3/c38fedb481c0a89eb25cb996e08d9f4c75e6aad3cc76853e99a830bc7355d319-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c3/c3cfae5535f44b948488a854137880661d34269f7d36526536a807aeabe37dff-a b/.cell-installs/xdg-cache/go-build/c3/c3cfae5535f44b948488a854137880661d34269f7d36526536a807aeabe37dff-a
new file mode 100644
index 0000000..a70776c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c3/c3cfae5535f44b948488a854137880661d34269f7d36526536a807aeabe37dff-a
@@ -0,0 +1 @@
+v1 c3cfae5535f44b948488a854137880661d34269f7d36526536a807aeabe37dff d9ef9079f14b3e47e5fbff492924f1a0d773d84dc132dc368d616cf83763c4d9               199772  1787953568823554313
diff --git a/.cell-installs/xdg-cache/go-build/c4/c48aaaeb3caa91e9a641e50c3b7e0651c6d6888829eb554cb1220c9207b6fbd0-d b/.cell-installs/xdg-cache/go-build/c4/c48aaaeb3caa91e9a641e50c3b7e0651c6d6888829eb554cb1220c9207b6fbd0-d
new file mode 100644
index 0000000..b4ec82a
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c4/c48aaaeb3caa91e9a641e50c3b7e0651c6d6888829eb554cb1220c9207b6fbd0-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c4/c4a1bdbc487d1e250c20bb838166a007e55d8014e60ae0e602b8500b0ea04676-a b/.cell-installs/xdg-cache/go-build/c4/c4a1bdbc487d1e250c20bb838166a007e55d8014e60ae0e602b8500b0ea04676-a
new file mode 100644
index 0000000..340b887
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c4/c4a1bdbc487d1e250c20bb838166a007e55d8014e60ae0e602b8500b0ea04676-a
@@ -0,0 +1 @@
+v1 c4a1bdbc487d1e250c20bb838166a007e55d8014e60ae0e602b8500b0ea04676 196bcb8298ec68e9fd730bcd530179198ad0bb5a00c940141fb400f951b3cdc8                  571  1787953775738798026
diff --git a/.cell-installs/xdg-cache/go-build/c4/c4adc29e06f70de05f9aa082fa9af8ffe44289c789247ebdce1f54f20ce67c8e-d b/.cell-installs/xdg-cache/go-build/c4/c4adc29e06f70de05f9aa082fa9af8ffe44289c789247ebdce1f54f20ce67c8e-d
new file mode 100644
index 0000000..cb1b08c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c4/c4adc29e06f70de05f9aa082fa9af8ffe44289c789247ebdce1f54f20ce67c8e-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c4/c4cf441dd2d7d1f08c86ad4a2fb4ce560b78a676903b84d88caaa2270c183579-d b/.cell-installs/xdg-cache/go-build/c4/c4cf441dd2d7d1f08c86ad4a2fb4ce560b78a676903b84d88caaa2270c183579-d
new file mode 100644
index 0000000..45309bc
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c4/c4cf441dd2d7d1f08c86ad4a2fb4ce560b78a676903b84d88caaa2270c183579-d
@@ -0,0 +1,2 @@
+./driver.go
+./types.go
diff --git a/.cell-installs/xdg-cache/go-build/c4/c4d15e9eaeab19516ec43aa4b60e459ce49daf55600559e3750a28941e894062-d b/.cell-installs/xdg-cache/go-build/c4/c4d15e9eaeab19516ec43aa4b60e459ce49daf55600559e3750a28941e894062-d
new file mode 100644
index 0000000..5c0b4ae
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c4/c4d15e9eaeab19516ec43aa4b60e459ce49daf55600559e3750a28941e894062-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c5/c527b8a5975959745b148a2000f3c523981a5d48ab37d39d5396b0aa7c71d1da-d b/.cell-installs/xdg-cache/go-build/c5/c527b8a5975959745b148a2000f3c523981a5d48ab37d39d5396b0aa7c71d1da-d
new file mode 100644
index 0000000..1d9b724
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c5/c527b8a5975959745b148a2000f3c523981a5d48ab37d39d5396b0aa7c71d1da-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c5/c5362dbec57ff461fa5a82fc34e086b2ae39f15f03f440e377c432d5559c9a45-d b/.cell-installs/xdg-cache/go-build/c5/c5362dbec57ff461fa5a82fc34e086b2ae39f15f03f440e377c432d5559c9a45-d
new file mode 100644
index 0000000..ae349eb
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c5/c5362dbec57ff461fa5a82fc34e086b2ae39f15f03f440e377c432d5559c9a45-d
@@ -0,0 +1,8 @@
+./ast.go
+./commentmap.go
+./filter.go
+./import.go
+./print.go
+./resolve.go
+./scope.go
+./walk.go
diff --git a/.cell-installs/xdg-cache/go-build/c5/c57be060ec648dd4a30517536339520007a04ce752b67b40b55f54a1a7df76b5-d b/.cell-installs/xdg-cache/go-build/c5/c57be060ec648dd4a30517536339520007a04ce752b67b40b55f54a1a7df76b5-d
new file mode 100644
index 0000000..e20c519
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c5/c57be060ec648dd4a30517536339520007a04ce752b67b40b55f54a1a7df76b5-d
@@ -0,0 +1 @@
+./utf8.go
diff --git a/.cell-installs/xdg-cache/go-build/c5/c58390b1ef97b635e2566119beb8f0bd25e616106d00838651b814cca4a66685-a b/.cell-installs/xdg-cache/go-build/c5/c58390b1ef97b635e2566119beb8f0bd25e616106d00838651b814cca4a66685-a
new file mode 100644
index 0000000..86552d0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c5/c58390b1ef97b635e2566119beb8f0bd25e616106d00838651b814cca4a66685-a
@@ -0,0 +1 @@
+v1 c58390b1ef97b635e2566119beb8f0bd25e616106d00838651b814cca4a66685 13ff642a7b1b7cb2e3cc1797bd3b141a03926c101408674befef2945a0e276d9                 1677  1787953170165839465
diff --git a/.cell-installs/xdg-cache/go-build/c5/c58df982bb46f9296ef46b27ed28f0a3ba1dc53ec82ed1f55b44c418c49f629a-d b/.cell-installs/xdg-cache/go-build/c5/c58df982bb46f9296ef46b27ed28f0a3ba1dc53ec82ed1f55b44c418c49f629a-d
new file mode 100644
index 0000000..d879391
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c5/c58df982bb46f9296ef46b27ed28f0a3ba1dc53ec82ed1f55b44c418c49f629a-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c5/c5b45d6563e21cddad9185599d9228491ceb1f364951c99b2a5febac6e43d7fe-a b/.cell-installs/xdg-cache/go-build/c5/c5b45d6563e21cddad9185599d9228491ceb1f364951c99b2a5febac6e43d7fe-a
new file mode 100644
index 0000000..e009099
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c5/c5b45d6563e21cddad9185599d9228491ceb1f364951c99b2a5febac6e43d7fe-a
@@ -0,0 +1 @@
+v1 c5b45d6563e21cddad9185599d9228491ceb1f364951c99b2a5febac6e43d7fe 5c3da9b34dfddd8c87523f59e7d8ed31a37954a01b54edc7a26328ec952ddcce                  969  1787953170148044857
diff --git a/.cell-installs/xdg-cache/go-build/c5/c5cdc4af37811f61e700df0bfcc0d006239feb27e06009cecb2756526c328794-d b/.cell-installs/xdg-cache/go-build/c5/c5cdc4af37811f61e700df0bfcc0d006239feb27e06009cecb2756526c328794-d
new file mode 100644
index 0000000..3f0ff01
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c5/c5cdc4af37811f61e700df0bfcc0d006239feb27e06009cecb2756526c328794-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c5/c5d589aecaffe8e4ee9dd0462061e10f091a0b9696dc82cfcef37d413efdca2b-a b/.cell-installs/xdg-cache/go-build/c5/c5d589aecaffe8e4ee9dd0462061e10f091a0b9696dc82cfcef37d413efdca2b-a
new file mode 100644
index 0000000..6291fc8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c5/c5d589aecaffe8e4ee9dd0462061e10f091a0b9696dc82cfcef37d413efdca2b-a
@@ -0,0 +1 @@
+v1 c5d589aecaffe8e4ee9dd0462061e10f091a0b9696dc82cfcef37d413efdca2b 0ce1b1d60f8a08833d55ed93fc8ee8fb07397702e6958b03f6f4ba7b55cc006d                   11  1787953567781327364
diff --git a/.cell-installs/xdg-cache/go-build/c6/c63bc32c2870d0100612a921070d3d9780bea53709afb3f362a1641567be5597-d b/.cell-installs/xdg-cache/go-build/c6/c63bc32c2870d0100612a921070d3d9780bea53709afb3f362a1641567be5597-d
new file mode 100644
index 0000000..dd9ca7e
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c6/c63bc32c2870d0100612a921070d3d9780bea53709afb3f362a1641567be5597-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c6/c642f211997e54b2aa9876258f2ffc617e33ae5555ae883cef8e0b91e72308ed-a b/.cell-installs/xdg-cache/go-build/c6/c642f211997e54b2aa9876258f2ffc617e33ae5555ae883cef8e0b91e72308ed-a
new file mode 100644
index 0000000..2df14f3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c6/c642f211997e54b2aa9876258f2ffc617e33ae5555ae883cef8e0b91e72308ed-a
@@ -0,0 +1 @@
+v1 c642f211997e54b2aa9876258f2ffc617e33ae5555ae883cef8e0b91e72308ed f5a87d177f954c3c21f6866840ba592bbe7a4ac35cdc378b350fa400dbe35758                75622  1787953568822460567
diff --git a/.cell-installs/xdg-cache/go-build/c6/c6b6aa81e49b1234859f2f8f6225898ea9db5baf924e831ba5c5c78933f2d6cd-a b/.cell-installs/xdg-cache/go-build/c6/c6b6aa81e49b1234859f2f8f6225898ea9db5baf924e831ba5c5c78933f2d6cd-a
new file mode 100644
index 0000000..1771204
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c6/c6b6aa81e49b1234859f2f8f6225898ea9db5baf924e831ba5c5c78933f2d6cd-a
@@ -0,0 +1 @@
+v1 c6b6aa81e49b1234859f2f8f6225898ea9db5baf924e831ba5c5c78933f2d6cd 196bcb8298ec68e9fd730bcd530179198ad0bb5a00c940141fb400f951b3cdc8                  571  1787954086822445016
diff --git a/.cell-installs/xdg-cache/go-build/c6/c6fce3e7622d1e337413abbd0789fc4032a4ffd99c4400cb811fadfa65d7b2b1-d b/.cell-installs/xdg-cache/go-build/c6/c6fce3e7622d1e337413abbd0789fc4032a4ffd99c4400cb811fadfa65d7b2b1-d
new file mode 100644
index 0000000..da7fcc5
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c6/c6fce3e7622d1e337413abbd0789fc4032a4ffd99c4400cb811fadfa65d7b2b1-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c7/c768e065e97dbe60b96d6d72db2158f20910eaae233f0431367c431966f3b12f-a b/.cell-installs/xdg-cache/go-build/c7/c768e065e97dbe60b96d6d72db2158f20910eaae233f0431367c431966f3b12f-a
new file mode 100644
index 0000000..bce79bc
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c7/c768e065e97dbe60b96d6d72db2158f20910eaae233f0431367c431966f3b12f-a
@@ -0,0 +1 @@
+v1 c768e065e97dbe60b96d6d72db2158f20910eaae233f0431367c431966f3b12f 1b948b86f6ffd7e620e9a500956155022108c921fd4d741113c19c21fdd6c98a                 1754  1787953771534555189
diff --git a/.cell-installs/xdg-cache/go-build/c7/c7a35068754d44eca4f9333fac0fbcd9c5a08a1a30fbcc2bbb71d54c5f2e72a2-a b/.cell-installs/xdg-cache/go-build/c7/c7a35068754d44eca4f9333fac0fbcd9c5a08a1a30fbcc2bbb71d54c5f2e72a2-a
new file mode 100644
index 0000000..3a59814
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c7/c7a35068754d44eca4f9333fac0fbcd9c5a08a1a30fbcc2bbb71d54c5f2e72a2-a
@@ -0,0 +1 @@
+v1 c7a35068754d44eca4f9333fac0fbcd9c5a08a1a30fbcc2bbb71d54c5f2e72a2 2afe7ad787290c2c39f05cf0108e4125051f96f73832d015c825eec70b05c35e                  805  1787953170155266717
diff --git a/.cell-installs/xdg-cache/go-build/c7/c7a4b30a20988d86ec3924c3c8f31826c504598826bd058164effe2f26ef99a2-a b/.cell-installs/xdg-cache/go-build/c7/c7a4b30a20988d86ec3924c3c8f31826c504598826bd058164effe2f26ef99a2-a
new file mode 100644
index 0000000..2f34e28
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c7/c7a4b30a20988d86ec3924c3c8f31826c504598826bd058164effe2f26ef99a2-a
@@ -0,0 +1 @@
+v1 c7a4b30a20988d86ec3924c3c8f31826c504598826bd058164effe2f26ef99a2 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569921275837
diff --git a/.cell-installs/xdg-cache/go-build/c8/c89dc1f87944c66479e4edb5ef09b5b69eae915f87a5ff82038606af224ca3ef-a b/.cell-installs/xdg-cache/go-build/c8/c89dc1f87944c66479e4edb5ef09b5b69eae915f87a5ff82038606af224ca3ef-a
new file mode 100644
index 0000000..6db943b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c8/c89dc1f87944c66479e4edb5ef09b5b69eae915f87a5ff82038606af224ca3ef-a
@@ -0,0 +1 @@
+v1 c89dc1f87944c66479e4edb5ef09b5b69eae915f87a5ff82038606af224ca3ef 0d2a0ba6eb9379c5ff0e137bc928ea099d76e9f61d9c2a2c591cb2aef5922e46                 7648  1787953567788118940
diff --git a/.cell-installs/xdg-cache/go-build/c8/c8e56a77356f1053a1c34cc2b7d06657bb954fbaf117c833c8e2f5a5f1700110-a b/.cell-installs/xdg-cache/go-build/c8/c8e56a77356f1053a1c34cc2b7d06657bb954fbaf117c833c8e2f5a5f1700110-a
new file mode 100644
index 0000000..20a8193
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c8/c8e56a77356f1053a1c34cc2b7d06657bb954fbaf117c833c8e2f5a5f1700110-a
@@ -0,0 +1 @@
+v1 c8e56a77356f1053a1c34cc2b7d06657bb954fbaf117c833c8e2f5a5f1700110 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569594856719
diff --git a/.cell-installs/xdg-cache/go-build/c9/c966d8fa9f16af621edc2d079251c83ec5f18501d22cd79aa30641a03befecd1-d b/.cell-installs/xdg-cache/go-build/c9/c966d8fa9f16af621edc2d079251c83ec5f18501d22cd79aa30641a03befecd1-d
new file mode 100644
index 0000000..6692ca2
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c9/c966d8fa9f16af621edc2d079251c83ec5f18501d22cd79aa30641a03befecd1-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c9/c97111b51ccea9f80d1a06f42e0940171da4c02ff28b8b87b7e419f45f415a02-d b/.cell-installs/xdg-cache/go-build/c9/c97111b51ccea9f80d1a06f42e0940171da4c02ff28b8b87b7e419f45f415a02-d
new file mode 100644
index 0000000..3a5e2e5
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c9/c97111b51ccea9f80d1a06f42e0940171da4c02ff28b8b87b7e419f45f415a02-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c9/c98c83cf2db7c5342e96a1feee7e676b9a4700437a4f21935a610535891b39a4-a b/.cell-installs/xdg-cache/go-build/c9/c98c83cf2db7c5342e96a1feee7e676b9a4700437a4f21935a610535891b39a4-a
new file mode 100644
index 0000000..babb8cf
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c9/c98c83cf2db7c5342e96a1feee7e676b9a4700437a4f21935a610535891b39a4-a
@@ -0,0 +1 @@
+v1 c98c83cf2db7c5342e96a1feee7e676b9a4700437a4f21935a610535891b39a4 d40e3d104d81d256c7a33c0feecdb2e57e6835346cef267147d73ebb97feff95                  318  1787953570307363069
diff --git a/.cell-installs/xdg-cache/go-build/c9/c9bf23b54fb7a607d75f5c772cb2a7d6dc283e3662d501531a238c6ca56d74ce-a b/.cell-installs/xdg-cache/go-build/c9/c9bf23b54fb7a607d75f5c772cb2a7d6dc283e3662d501531a238c6ca56d74ce-a
new file mode 100644
index 0000000..3014ee0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c9/c9bf23b54fb7a607d75f5c772cb2a7d6dc283e3662d501531a238c6ca56d74ce-a
@@ -0,0 +1 @@
+v1 c9bf23b54fb7a607d75f5c772cb2a7d6dc283e3662d501531a238c6ca56d74ce 952838e8dfa7e8fe8f1908376028275e0cd76022e77d3df6b18cc02e5999defa                  609  1787953170191226923
diff --git a/.cell-installs/xdg-cache/go-build/c9/c9c7a36b99e82be6026278e83ffa9c973a2b21191d85c21318f8f88141eae809-a b/.cell-installs/xdg-cache/go-build/c9/c9c7a36b99e82be6026278e83ffa9c973a2b21191d85c21318f8f88141eae809-a
new file mode 100644
index 0000000..3b4f08c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c9/c9c7a36b99e82be6026278e83ffa9c973a2b21191d85c21318f8f88141eae809-a
@@ -0,0 +1 @@
+v1 c9c7a36b99e82be6026278e83ffa9c973a2b21191d85c21318f8f88141eae809 c5cdc4af37811f61e700df0bfcc0d006239feb27e06009cecb2756526c328794                95028  1787953569128486639
diff --git a/.cell-installs/xdg-cache/go-build/c9/c9cc8c2d7a0e359e18aca0c149d3922eca434c29c0e3ad7c92ea2ca4d0802a4d-d b/.cell-installs/xdg-cache/go-build/c9/c9cc8c2d7a0e359e18aca0c149d3922eca434c29c0e3ad7c92ea2ca4d0802a4d-d
new file mode 100644
index 0000000..1ac1f40
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c9/c9cc8c2d7a0e359e18aca0c149d3922eca434c29c0e3ad7c92ea2ca4d0802a4d-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c9/c9e606d004cc52dc1cdab23e1466ec305f9e53462c296e6eb2c3ee4595d0718f-d b/.cell-installs/xdg-cache/go-build/c9/c9e606d004cc52dc1cdab23e1466ec305f9e53462c296e6eb2c3ee4595d0718f-d
new file mode 100644
index 0000000..45124a5
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/c9/c9e606d004cc52dc1cdab23e1466ec305f9e53462c296e6eb2c3ee4595d0718f-d differ
diff --git a/.cell-installs/xdg-cache/go-build/c9/c9f0e4b6d8fbf7eff708f6cc82b6fea4c118bb7671ebfbf600b55cb7a916d7c3-a b/.cell-installs/xdg-cache/go-build/c9/c9f0e4b6d8fbf7eff708f6cc82b6fea4c118bb7671ebfbf600b55cb7a916d7c3-a
new file mode 100644
index 0000000..1737082
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/c9/c9f0e4b6d8fbf7eff708f6cc82b6fea4c118bb7671ebfbf600b55cb7a916d7c3-a
@@ -0,0 +1 @@
+v1 c9f0e4b6d8fbf7eff708f6cc82b6fea4c118bb7671ebfbf600b55cb7a916d7c3 0ade478c47682faf58a52859f6db10681be1a74a2410f86c57a51426afeac837                 7472  1787953153951947529
diff --git a/.cell-installs/xdg-cache/go-build/ca/ca553b69c1e20a6bb50bd0c8bfb362f274c54fd914a5b1d3e2205c2e2d4e0986-a b/.cell-installs/xdg-cache/go-build/ca/ca553b69c1e20a6bb50bd0c8bfb362f274c54fd914a5b1d3e2205c2e2d4e0986-a
new file mode 100644
index 0000000..f5da9c2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ca/ca553b69c1e20a6bb50bd0c8bfb362f274c54fd914a5b1d3e2205c2e2d4e0986-a
@@ -0,0 +1 @@
+v1 ca553b69c1e20a6bb50bd0c8bfb362f274c54fd914a5b1d3e2205c2e2d4e0986 06a45522df397b46b35bf32c99a6897f0e05a1628f940c5c48517ecab0a791ff                   15  1787953569876738633
diff --git a/.cell-installs/xdg-cache/go-build/cb/cb08f3cecc384625c6ac22d25f071469b04364db5ed59b9d4c828111fb81e085-a b/.cell-installs/xdg-cache/go-build/cb/cb08f3cecc384625c6ac22d25f071469b04364db5ed59b9d4c828111fb81e085-a
new file mode 100644
index 0000000..8fd7a40
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/cb/cb08f3cecc384625c6ac22d25f071469b04364db5ed59b9d4c828111fb81e085-a
@@ -0,0 +1 @@
+v1 cb08f3cecc384625c6ac22d25f071469b04364db5ed59b9d4c828111fb81e085 220c3eb368a151d62abea6651ea4c9d88bd44a713538b70de897ee21ff53529c                   41  1787953570076003256
diff --git a/.cell-installs/xdg-cache/go-build/cb/cbca567be2e044f31d62c5c4202d38d2ab718a6788946ce1edf6d6ae5e2d45be-d b/.cell-installs/xdg-cache/go-build/cb/cbca567be2e044f31d62c5c4202d38d2ab718a6788946ce1edf6d6ae5e2d45be-d
new file mode 100644
index 0000000..8bfa084
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/cb/cbca567be2e044f31d62c5c4202d38d2ab718a6788946ce1edf6d6ae5e2d45be-d differ
diff --git a/.cell-installs/xdg-cache/go-build/cc/cc2e5cfa91e1e68a1d8be99f1f5771850309bd225cef8abc2c10aa560be938e4-a b/.cell-installs/xdg-cache/go-build/cc/cc2e5cfa91e1e68a1d8be99f1f5771850309bd225cef8abc2c10aa560be938e4-a
new file mode 100644
index 0000000..3c5f66a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/cc/cc2e5cfa91e1e68a1d8be99f1f5771850309bd225cef8abc2c10aa560be938e4-a
@@ -0,0 +1 @@
+v1 cc2e5cfa91e1e68a1d8be99f1f5771850309bd225cef8abc2c10aa560be938e4 811a8fa82ebb2ea19a98b5fde95a47bd932e6ee791652aeeae7b7bb0dd674ece                 1713  1787953771571351015
diff --git a/.cell-installs/xdg-cache/go-build/cc/ccc9ef80ed81775660515bc5b31474f4af3178367d75e06e24f8904acad899c5-a b/.cell-installs/xdg-cache/go-build/cc/ccc9ef80ed81775660515bc5b31474f4af3178367d75e06e24f8904acad899c5-a
new file mode 100644
index 0000000..5aa49f7
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/cc/ccc9ef80ed81775660515bc5b31474f4af3178367d75e06e24f8904acad899c5-a
@@ -0,0 +1 @@
+v1 ccc9ef80ed81775660515bc5b31474f4af3178367d75e06e24f8904acad899c5 64f35a0d4962a7b524febc64efe58aac7d6140e25127d71a0b51e5d3a2cdf432               261278  1787953569907653351
diff --git a/.cell-installs/xdg-cache/go-build/cd/cd5800133b83a091698161c3864caa4bc30e2ee9a3a569f593244cbc6be11e43-a b/.cell-installs/xdg-cache/go-build/cd/cd5800133b83a091698161c3864caa4bc30e2ee9a3a569f593244cbc6be11e43-a
new file mode 100644
index 0000000..b3b73ee
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/cd/cd5800133b83a091698161c3864caa4bc30e2ee9a3a569f593244cbc6be11e43-a
@@ -0,0 +1 @@
+v1 cd5800133b83a091698161c3864caa4bc30e2ee9a3a569f593244cbc6be11e43 da27a2c4c47c054b263dcb340bdb17831c442c8b6fddab248fa88c934d71fc0a                22144  1787953569872535288
diff --git a/.cell-installs/xdg-cache/go-build/cd/cd5b2b9c8b9d6337647d64f46ebf4dfb3e9f4158cc94c4af9698712484c12f81-a b/.cell-installs/xdg-cache/go-build/cd/cd5b2b9c8b9d6337647d64f46ebf4dfb3e9f4158cc94c4af9698712484c12f81-a
new file mode 100644
index 0000000..8882e3f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/cd/cd5b2b9c8b9d6337647d64f46ebf4dfb3e9f4158cc94c4af9698712484c12f81-a
@@ -0,0 +1 @@
+v1 cd5b2b9c8b9d6337647d64f46ebf4dfb3e9f4158cc94c4af9698712484c12f81 abf9b086954be97a8a7e7baf77f11366040bd28741499c6ce1d0f6c934be44d6                  542  1787953568829400838
diff --git a/.cell-installs/xdg-cache/go-build/cd/cd5b49557d0254b87e3a6b8ea790363e8672a204d74c79f13e1b0d01e9694eed-d b/.cell-installs/xdg-cache/go-build/cd/cd5b49557d0254b87e3a6b8ea790363e8672a204d74c79f13e1b0d01e9694eed-d
new file mode 100644
index 0000000..73169cb
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/cd/cd5b49557d0254b87e3a6b8ea790363e8672a204d74c79f13e1b0d01e9694eed-d differ
diff --git a/.cell-installs/xdg-cache/go-build/cd/cd5e7b9bf6f7c840d4a9a3aa8d91a1dcd5773640cad39b2e04dd8cfa493a76b1-a b/.cell-installs/xdg-cache/go-build/cd/cd5e7b9bf6f7c840d4a9a3aa8d91a1dcd5773640cad39b2e04dd8cfa493a76b1-a
new file mode 100644
index 0000000..c7d45a4
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/cd/cd5e7b9bf6f7c840d4a9a3aa8d91a1dcd5773640cad39b2e04dd8cfa493a76b1-a
@@ -0,0 +1 @@
+v1 cd5e7b9bf6f7c840d4a9a3aa8d91a1dcd5773640cad39b2e04dd8cfa493a76b1 ae447828aa56d629c781aa1fb8974b5665641f7dd6192562860fe575fb4f79d7                 7712  1787953569875352252
diff --git a/.cell-installs/xdg-cache/go-build/cd/cdeac5984c1defe3f74ba3a7dd9384a3ebd04d96a1f0be639b6aed4bd434d478-d b/.cell-installs/xdg-cache/go-build/cd/cdeac5984c1defe3f74ba3a7dd9384a3ebd04d96a1f0be639b6aed4bd434d478-d
new file mode 100644
index 0000000..9836e3e
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/cd/cdeac5984c1defe3f74ba3a7dd9384a3ebd04d96a1f0be639b6aed4bd434d478-d differ
diff --git a/.cell-installs/xdg-cache/go-build/ce/ceb6818795925b32ec5a200af185f1663e48fcc6ab5e62b6062f608e71b3b5be-a b/.cell-installs/xdg-cache/go-build/ce/ceb6818795925b32ec5a200af185f1663e48fcc6ab5e62b6062f608e71b3b5be-a
new file mode 100644
index 0000000..85cea49
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ce/ceb6818795925b32ec5a200af185f1663e48fcc6ab5e62b6062f608e71b3b5be-a
@@ -0,0 +1 @@
+v1 ceb6818795925b32ec5a200af185f1663e48fcc6ab5e62b6062f608e71b3b5be 05f5e6492430b00f807e4629c6e4a53f3948fc9382f19898d1cc361b3b99ff9b                   54  1787953569236306301
diff --git a/.cell-installs/xdg-cache/go-build/ce/cecf34c8c3fefe9efaba77f3fc7bc5b6108af4d2e752dc25e10fc4d04c2ae39a-d b/.cell-installs/xdg-cache/go-build/ce/cecf34c8c3fefe9efaba77f3fc7bc5b6108af4d2e752dc25e10fc4d04c2ae39a-d
new file mode 100644
index 0000000..5694ab8
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/ce/cecf34c8c3fefe9efaba77f3fc7bc5b6108af4d2e752dc25e10fc4d04c2ae39a-d differ
diff --git a/.cell-installs/xdg-cache/go-build/cf/cf3c12dec4f83399b7b5a5bc5d7aee01352a18688523d10d4196a81290a5b156-a b/.cell-installs/xdg-cache/go-build/cf/cf3c12dec4f83399b7b5a5bc5d7aee01352a18688523d10d4196a81290a5b156-a
new file mode 100644
index 0000000..44c7ffe
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/cf/cf3c12dec4f83399b7b5a5bc5d7aee01352a18688523d10d4196a81290a5b156-a
@@ -0,0 +1 @@
+v1 cf3c12dec4f83399b7b5a5bc5d7aee01352a18688523d10d4196a81290a5b156 a8980058458adc26933415a4ab8d77ec49556ba2430ee6cb63f7d27d2dd1e098                  364  1787953170149138146
diff --git a/.cell-installs/xdg-cache/go-build/cf/cf50bb48fec76bd80aa99c07f728ac78304203e7c9d41627356bb4136389efcd-d b/.cell-installs/xdg-cache/go-build/cf/cf50bb48fec76bd80aa99c07f728ac78304203e7c9d41627356bb4136389efcd-d
new file mode 100644
index 0000000..f93b193
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/cf/cf50bb48fec76bd80aa99c07f728ac78304203e7c9d41627356bb4136389efcd-d differ
diff --git a/.cell-installs/xdg-cache/go-build/cf/cfd65274f1781c3de977a870a2bab3f26d685c9e7a8ccacf0997738371d14d00-a b/.cell-installs/xdg-cache/go-build/cf/cfd65274f1781c3de977a870a2bab3f26d685c9e7a8ccacf0997738371d14d00-a
new file mode 100644
index 0000000..675e464
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/cf/cfd65274f1781c3de977a870a2bab3f26d685c9e7a8ccacf0997738371d14d00-a
@@ -0,0 +1 @@
+v1 cfd65274f1781c3de977a870a2bab3f26d685c9e7a8ccacf0997738371d14d00 955e4e1a715bc958121e1184f5b9c9456a936ff95bf433850edb5f269624c3d8                 1917  1787953170150132903
diff --git a/.cell-installs/xdg-cache/go-build/d0/d062a0af5987ea4eb6b837c877b2d32de92b2b2c52fda7e41ff8f58ec66ee8fb-d b/.cell-installs/xdg-cache/go-build/d0/d062a0af5987ea4eb6b837c877b2d32de92b2b2c52fda7e41ff8f58ec66ee8fb-d
new file mode 100644
index 0000000..bf2f1fa
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/d0/d062a0af5987ea4eb6b837c877b2d32de92b2b2c52fda7e41ff8f58ec66ee8fb-d differ
diff --git a/.cell-installs/xdg-cache/go-build/d0/d0c8137e23307fae68aa51b1ea0a506dd4b29743bbe4d3a4efca398b0f3cd246-a b/.cell-installs/xdg-cache/go-build/d0/d0c8137e23307fae68aa51b1ea0a506dd4b29743bbe4d3a4efca398b0f3cd246-a
new file mode 100644
index 0000000..13c2f1f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d0/d0c8137e23307fae68aa51b1ea0a506dd4b29743bbe4d3a4efca398b0f3cd246-a
@@ -0,0 +1 @@
+v1 d0c8137e23307fae68aa51b1ea0a506dd4b29743bbe4d3a4efca398b0f3cd246 1d34dfde1a097165d2e5f6c14c2280687899d163868539ec093f6857366c0f20                 1577  1787953170162567083
diff --git a/.cell-installs/xdg-cache/go-build/d1/d12ad4c5dafeffd94eace65d3cfad8ae8ce2f13b8dc59c9ed8be5e00522d6d5d-d b/.cell-installs/xdg-cache/go-build/d1/d12ad4c5dafeffd94eace65d3cfad8ae8ce2f13b8dc59c9ed8be5e00522d6d5d-d
new file mode 100644
index 0000000..f79d681
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/d1/d12ad4c5dafeffd94eace65d3cfad8ae8ce2f13b8dc59c9ed8be5e00522d6d5d-d differ
diff --git a/.cell-installs/xdg-cache/go-build/d1/d14757b3fa89f91ddfb847f6f91219a98a2596cce1ef9fd0824fa12ee0897779-a b/.cell-installs/xdg-cache/go-build/d1/d14757b3fa89f91ddfb847f6f91219a98a2596cce1ef9fd0824fa12ee0897779-a
new file mode 100644
index 0000000..f8344d3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d1/d14757b3fa89f91ddfb847f6f91219a98a2596cce1ef9fd0824fa12ee0897779-a
@@ -0,0 +1 @@
+v1 d14757b3fa89f91ddfb847f6f91219a98a2596cce1ef9fd0824fa12ee0897779 830e06d9b0a0005e03ffc34da06ec8452e2d981a0850d67ced4c5a18d18f6046                 3309  1787953153944097748
diff --git a/.cell-installs/xdg-cache/go-build/d1/d16ed900a1cfae04df21d0df19e34c695abd4c00d436850a224ff63a1de4638a-a b/.cell-installs/xdg-cache/go-build/d1/d16ed900a1cfae04df21d0df19e34c695abd4c00d436850a224ff63a1de4638a-a
new file mode 100644
index 0000000..dc901c2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d1/d16ed900a1cfae04df21d0df19e34c695abd4c00d436850a224ff63a1de4638a-a
@@ -0,0 +1 @@
+v1 d16ed900a1cfae04df21d0df19e34c695abd4c00d436850a224ff63a1de4638a 86adbbb15c53775a99f62697b7e04b4648ccd5ae09c2ebf3916c7f1aa915148c                  535  1787953352788518513
diff --git a/.cell-installs/xdg-cache/go-build/d1/d18d3e26563af5819d828eab66cfbd457d84b273c574048283e05f48e187953c-a b/.cell-installs/xdg-cache/go-build/d1/d18d3e26563af5819d828eab66cfbd457d84b273c574048283e05f48e187953c-a
new file mode 100644
index 0000000..74378d8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d1/d18d3e26563af5819d828eab66cfbd457d84b273c574048283e05f48e187953c-a
@@ -0,0 +1 @@
+v1 d18d3e26563af5819d828eab66cfbd457d84b273c574048283e05f48e187953c 28a889188865860b36c0ed3b88375c60e26f77d434380e17473e54228ac14a40                 1712  1787953771569350470
diff --git a/.cell-installs/xdg-cache/go-build/d2/d2061a60090bd0155e6d7dcd61baa775ec78702c54dfaecd1a32cb16e49038ac-a b/.cell-installs/xdg-cache/go-build/d2/d2061a60090bd0155e6d7dcd61baa775ec78702c54dfaecd1a32cb16e49038ac-a
new file mode 100644
index 0000000..0a6e51b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d2/d2061a60090bd0155e6d7dcd61baa775ec78702c54dfaecd1a32cb16e49038ac-a
@@ -0,0 +1 @@
+v1 d2061a60090bd0155e6d7dcd61baa775ec78702c54dfaecd1a32cb16e49038ac 7ccbc779ad26b1b2a2236e142440cd26fa54504420cdb9400cc8a18617b5086f                 5188  1787953170159647716
diff --git a/.cell-installs/xdg-cache/go-build/d2/d20e2a247e7b961dae1e41d4820cd0f0ef23ed55436bd2151d6bbd307a880818-d b/.cell-installs/xdg-cache/go-build/d2/d20e2a247e7b961dae1e41d4820cd0f0ef23ed55436bd2151d6bbd307a880818-d
new file mode 100644
index 0000000..4a474a5
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/d2/d20e2a247e7b961dae1e41d4820cd0f0ef23ed55436bd2151d6bbd307a880818-d differ
diff --git a/.cell-installs/xdg-cache/go-build/d2/d2c0732505a8cc6adee757c96e7c079bab57e3700d4489d98bccf0a53a920263-a b/.cell-installs/xdg-cache/go-build/d2/d2c0732505a8cc6adee757c96e7c079bab57e3700d4489d98bccf0a53a920263-a
new file mode 100644
index 0000000..a22fd08
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d2/d2c0732505a8cc6adee757c96e7c079bab57e3700d4489d98bccf0a53a920263-a
@@ -0,0 +1 @@
+v1 d2c0732505a8cc6adee757c96e7c079bab57e3700d4489d98bccf0a53a920263 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569320662581
diff --git a/.cell-installs/xdg-cache/go-build/d3/d324f89a3d74cdb5ad955f60adef46996feb7786cf218d8bbe82f684c5174a56-a b/.cell-installs/xdg-cache/go-build/d3/d324f89a3d74cdb5ad955f60adef46996feb7786cf218d8bbe82f684c5174a56-a
new file mode 100644
index 0000000..f74fc17
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d3/d324f89a3d74cdb5ad955f60adef46996feb7786cf218d8bbe82f684c5174a56-a
@@ -0,0 +1 @@
+v1 d324f89a3d74cdb5ad955f60adef46996feb7786cf218d8bbe82f684c5174a56 da6c44b2002e7afb4a39ff6adf36ab31705efc3eea08d273b8cb4e4837394579                53104  1787953154017209885
diff --git a/.cell-installs/xdg-cache/go-build/d3/d35ab5ee879cc0291c90925d87d6bc314706fccedb3a534d810db486d89b63de-a b/.cell-installs/xdg-cache/go-build/d3/d35ab5ee879cc0291c90925d87d6bc314706fccedb3a534d810db486d89b63de-a
new file mode 100644
index 0000000..972295c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d3/d35ab5ee879cc0291c90925d87d6bc314706fccedb3a534d810db486d89b63de-a
@@ -0,0 +1 @@
+v1 d35ab5ee879cc0291c90925d87d6bc314706fccedb3a534d810db486d89b63de e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567786512015
diff --git a/.cell-installs/xdg-cache/go-build/d3/d3b329695dbc5c9fd0c8a7bdaf0c16039960afdb66f109dcf0013014946d6102-a b/.cell-installs/xdg-cache/go-build/d3/d3b329695dbc5c9fd0c8a7bdaf0c16039960afdb66f109dcf0013014946d6102-a
new file mode 100644
index 0000000..7ef5383
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d3/d3b329695dbc5c9fd0c8a7bdaf0c16039960afdb66f109dcf0013014946d6102-a
@@ -0,0 +1 @@
+v1 d3b329695dbc5c9fd0c8a7bdaf0c16039960afdb66f109dcf0013014946d6102 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569318477263
diff --git a/.cell-installs/xdg-cache/go-build/d3/d3f21047470b949bde25adaa11dec4f8bb3dad35cf0efe10be000340862891cb-d b/.cell-installs/xdg-cache/go-build/d3/d3f21047470b949bde25adaa11dec4f8bb3dad35cf0efe10be000340862891cb-d
new file mode 100644
index 0000000..0eb117e
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d3/d3f21047470b949bde25adaa11dec4f8bb3dad35cf0efe10be000340862891cb-d
@@ -0,0 +1,8 @@
+./decode.go
+./encode.go
+./fold.go
+./indent.go
+./scanner.go
+./stream.go
+./tables.go
+./tags.go
diff --git a/.cell-installs/xdg-cache/go-build/d4/d40e3d104d81d256c7a33c0feecdb2e57e6835346cef267147d73ebb97feff95-d b/.cell-installs/xdg-cache/go-build/d4/d40e3d104d81d256c7a33c0feecdb2e57e6835346cef267147d73ebb97feff95-d
new file mode 100644
index 0000000..89a3005
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/d4/d40e3d104d81d256c7a33c0feecdb2e57e6835346cef267147d73ebb97feff95-d differ
diff --git a/.cell-installs/xdg-cache/go-build/d4/d43c84f157560540a3afbd6f5fd357f3a9e1226ac566ef85bcb8822ebff4c25c-d b/.cell-installs/xdg-cache/go-build/d4/d43c84f157560540a3afbd6f5fd357f3a9e1226ac566ef85bcb8822ebff4c25c-d
new file mode 100644
index 0000000..b05f835
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/d4/d43c84f157560540a3afbd6f5fd357f3a9e1226ac566ef85bcb8822ebff4c25c-d differ
diff --git a/.cell-installs/xdg-cache/go-build/d4/d46d427cbe9b5714606c4c51ee199a241f532e3b268bdabc3217e2395dd60fd4-a b/.cell-installs/xdg-cache/go-build/d4/d46d427cbe9b5714606c4c51ee199a241f532e3b268bdabc3217e2395dd60fd4-a
new file mode 100644
index 0000000..1986b64
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d4/d46d427cbe9b5714606c4c51ee199a241f532e3b268bdabc3217e2395dd60fd4-a
@@ -0,0 +1 @@
+v1 d46d427cbe9b5714606c4c51ee199a241f532e3b268bdabc3217e2395dd60fd4 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570199142721
diff --git a/.cell-installs/xdg-cache/go-build/d4/d46e6d4563157ccf8b1e729517f632653a0993aa459d0b46c8c94eac7b9cc410-a b/.cell-installs/xdg-cache/go-build/d4/d46e6d4563157ccf8b1e729517f632653a0993aa459d0b46c8c94eac7b9cc410-a
new file mode 100644
index 0000000..551ac52
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d4/d46e6d4563157ccf8b1e729517f632653a0993aa459d0b46c8c94eac7b9cc410-a
@@ -0,0 +1 @@
+v1 d46e6d4563157ccf8b1e729517f632653a0993aa459d0b46c8c94eac7b9cc410 fc86703776a7cc6694bd264e07d06fada19834ad7b7ae843c10e69a72976ea66                  477  1787953153950807516
diff --git a/.cell-installs/xdg-cache/go-build/d4/d4f6870cc387540460f514ffa83b518c81636cb4f7a328fc2e25f7bd7bbf7205-a b/.cell-installs/xdg-cache/go-build/d4/d4f6870cc387540460f514ffa83b518c81636cb4f7a328fc2e25f7bd7bbf7205-a
new file mode 100644
index 0000000..41908e4
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d4/d4f6870cc387540460f514ffa83b518c81636cb4f7a328fc2e25f7bd7bbf7205-a
@@ -0,0 +1 @@
+v1 d4f6870cc387540460f514ffa83b518c81636cb4f7a328fc2e25f7bd7bbf7205 c58df982bb46f9296ef46b27ed28f0a3ba1dc53ec82ed1f55b44c418c49f629a                 2725  1787953771573566218
diff --git a/.cell-installs/xdg-cache/go-build/d5/d50b93e6e088c00aa72b32183fad722ad8f8af61be5747518fadd1eb36d8598c-d b/.cell-installs/xdg-cache/go-build/d5/d50b93e6e088c00aa72b32183fad722ad8f8af61be5747518fadd1eb36d8598c-d
new file mode 100644
index 0000000..720cfb3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d5/d50b93e6e088c00aa72b32183fad722ad8f8af61be5747518fadd1eb36d8598c-d
@@ -0,0 +1,18 @@
+./exp_allocheaders_on.go
+./exp_arenas_off.go
+./exp_boringcrypto_off.go
+./exp_cacheprog_off.go
+./exp_cgocheck2_off.go
+./exp_coverageredesign_on.go
+./exp_exectracer2_on.go
+./exp_fieldtrack_off.go
+./exp_heapminimum512kib_off.go
+./exp_loopvar_off.go
+./exp_newinliner_off.go
+./exp_pagetrace_off.go
+./exp_preemptibleloops_off.go
+./exp_rangefunc_off.go
+./exp_regabiargs_on.go
+./exp_regabiwrappers_on.go
+./exp_staticlockranking_off.go
+./flags.go
diff --git a/.cell-installs/xdg-cache/go-build/d5/d552b33626d29e82f002a3f54415f193a5dbb3c7b1234b53e46d2a4812c50def-d b/.cell-installs/xdg-cache/go-build/d5/d552b33626d29e82f002a3f54415f193a5dbb3c7b1234b53e46d2a4812c50def-d
new file mode 100644
index 0000000..bd4236c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/d5/d552b33626d29e82f002a3f54415f193a5dbb3c7b1234b53e46d2a4812c50def-d differ
diff --git a/.cell-installs/xdg-cache/go-build/d5/d5aaa3589d0dd0f52656e7e1b1954ff20ba87ada974c5858fa8e5e0fc830ac52-d b/.cell-installs/xdg-cache/go-build/d5/d5aaa3589d0dd0f52656e7e1b1954ff20ba87ada974c5858fa8e5e0fc830ac52-d
new file mode 100644
index 0000000..bc80ba7
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/d5/d5aaa3589d0dd0f52656e7e1b1954ff20ba87ada974c5858fa8e5e0fc830ac52-d differ
diff --git a/.cell-installs/xdg-cache/go-build/d6/d64607ea859d0cd084d5b42d7c2428c4232d8a87b8ffd8c2609db4b4893bded0-a b/.cell-installs/xdg-cache/go-build/d6/d64607ea859d0cd084d5b42d7c2428c4232d8a87b8ffd8c2609db4b4893bded0-a
new file mode 100644
index 0000000..1d4ee8a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d6/d64607ea859d0cd084d5b42d7c2428c4232d8a87b8ffd8c2609db4b4893bded0-a
@@ -0,0 +1 @@
+v1 d64607ea859d0cd084d5b42d7c2428c4232d8a87b8ffd8c2609db4b4893bded0 611333b6e0e9f3f6dd155b886debd7decd0cee8d533ce45e057452e54b50aaaa                  101  1787953569877817338
diff --git a/.cell-installs/xdg-cache/go-build/d6/d6697faf1f2698551afdd5e6cecb79a6a53e9585f97a3e3ee43a2aaeb4ee4142-a b/.cell-installs/xdg-cache/go-build/d6/d6697faf1f2698551afdd5e6cecb79a6a53e9585f97a3e3ee43a2aaeb4ee4142-a
new file mode 100644
index 0000000..b76b758
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d6/d6697faf1f2698551afdd5e6cecb79a6a53e9585f97a3e3ee43a2aaeb4ee4142-a
@@ -0,0 +1 @@
+v1 d6697faf1f2698551afdd5e6cecb79a6a53e9585f97a3e3ee43a2aaeb4ee4142 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568886314041
diff --git a/.cell-installs/xdg-cache/go-build/d6/d6ae6443826e9de9b932d2cd3f5431a2c0823dbf8165f4ec13f7f2b1318edb26-d b/.cell-installs/xdg-cache/go-build/d6/d6ae6443826e9de9b932d2cd3f5431a2c0823dbf8165f4ec13f7f2b1318edb26-d
new file mode 100644
index 0000000..ebb2e7a
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/d6/d6ae6443826e9de9b932d2cd3f5431a2c0823dbf8165f4ec13f7f2b1318edb26-d differ
diff --git a/.cell-installs/xdg-cache/go-build/d7/d75ed97c20e1aa4718e332a366eeb08d5d54cd114711701963c70897dc0fab55-d b/.cell-installs/xdg-cache/go-build/d7/d75ed97c20e1aa4718e332a366eeb08d5d54cd114711701963c70897dc0fab55-d
new file mode 100644
index 0000000..c5642be
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/d7/d75ed97c20e1aa4718e332a366eeb08d5d54cd114711701963c70897dc0fab55-d differ
diff --git a/.cell-installs/xdg-cache/go-build/d7/d7706a628a7a584296284adebc189baba664690fd5b73451f13e7bfdd738f269-a b/.cell-installs/xdg-cache/go-build/d7/d7706a628a7a584296284adebc189baba664690fd5b73451f13e7bfdd738f269-a
new file mode 100644
index 0000000..3edab29
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d7/d7706a628a7a584296284adebc189baba664690fd5b73451f13e7bfdd738f269-a
@@ -0,0 +1 @@
+v1 d7706a628a7a584296284adebc189baba664690fd5b73451f13e7bfdd738f269 d50b93e6e088c00aa72b32183fad722ad8f8af61be5747518fadd1eb36d8598c                  438  1787953567782935059
diff --git a/.cell-installs/xdg-cache/go-build/d7/d7ac2dd2e2ff8c8082d041ed77623fdde96350912028ce152668212240e70581-a b/.cell-installs/xdg-cache/go-build/d7/d7ac2dd2e2ff8c8082d041ed77623fdde96350912028ce152668212240e70581-a
new file mode 100644
index 0000000..18e02b5
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d7/d7ac2dd2e2ff8c8082d041ed77623fdde96350912028ce152668212240e70581-a
@@ -0,0 +1 @@
+v1 d7ac2dd2e2ff8c8082d041ed77623fdde96350912028ce152668212240e70581 c63bc32c2870d0100612a921070d3d9780bea53709afb3f362a1641567be5597                 1275  1787953170180910194
diff --git a/.cell-installs/xdg-cache/go-build/d7/d7d40f3b7dd2d602a93228601bd7c2b2e01ea4432159bfe26dd61f97fb87a9b6-a b/.cell-installs/xdg-cache/go-build/d7/d7d40f3b7dd2d602a93228601bd7c2b2e01ea4432159bfe26dd61f97fb87a9b6-a
new file mode 100644
index 0000000..4e3b785
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d7/d7d40f3b7dd2d602a93228601bd7c2b2e01ea4432159bfe26dd61f97fb87a9b6-a
@@ -0,0 +1 @@
+v1 d7d40f3b7dd2d602a93228601bd7c2b2e01ea4432159bfe26dd61f97fb87a9b6 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569318408821
diff --git a/.cell-installs/xdg-cache/go-build/d7/d7e3e47358719b37eb4f24ee2c6f9247104ae1f2e06f32f93d1f63842b4cbfdb-d b/.cell-installs/xdg-cache/go-build/d7/d7e3e47358719b37eb4f24ee2c6f9247104ae1f2e06f32f93d1f63842b4cbfdb-d
new file mode 100644
index 0000000..7bb10e8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d7/d7e3e47358719b37eb4f24ee2c6f9247104ae1f2e06f32f93d1f63842b4cbfdb-d
@@ -0,0 +1,6 @@
+./match.go
+./path.go
+./path_nonwindows.go
+./path_unix.go
+./symlink.go
+./symlink_unix.go
diff --git a/.cell-installs/xdg-cache/go-build/d8/d80dbfc9aaa348c9ffb73f1453dc75fb04e677b5487c3d53020a28f407aaed53-a b/.cell-installs/xdg-cache/go-build/d8/d80dbfc9aaa348c9ffb73f1453dc75fb04e677b5487c3d53020a28f407aaed53-a
new file mode 100644
index 0000000..ef1e4c9
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d8/d80dbfc9aaa348c9ffb73f1453dc75fb04e677b5487c3d53020a28f407aaed53-a
@@ -0,0 +1 @@
+v1 d80dbfc9aaa348c9ffb73f1453dc75fb04e677b5487c3d53020a28f407aaed53 7108bc836ff13c376ecf070ba50c1bfafd3e90a39acb2397fe45d769973f09ac                  639  1787953567724696427
diff --git a/.cell-installs/xdg-cache/go-build/d8/d81dc8039a91b6bfd76d726cbd60c9137039982794592f3e73e5e7dbf1b3f425-a b/.cell-installs/xdg-cache/go-build/d8/d81dc8039a91b6bfd76d726cbd60c9137039982794592f3e73e5e7dbf1b3f425-a
new file mode 100644
index 0000000..d911414
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d8/d81dc8039a91b6bfd76d726cbd60c9137039982794592f3e73e5e7dbf1b3f425-a
@@ -0,0 +1 @@
+v1 d81dc8039a91b6bfd76d726cbd60c9137039982794592f3e73e5e7dbf1b3f425 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568828823327
diff --git a/.cell-installs/xdg-cache/go-build/d8/d834051268d5021a4a8a6b7e204560f3054a70f36c794ebcc68252cec388f4c1-a b/.cell-installs/xdg-cache/go-build/d8/d834051268d5021a4a8a6b7e204560f3054a70f36c794ebcc68252cec388f4c1-a
new file mode 100644
index 0000000..6981d9a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d8/d834051268d5021a4a8a6b7e204560f3054a70f36c794ebcc68252cec388f4c1-a
@@ -0,0 +1 @@
+v1 d834051268d5021a4a8a6b7e204560f3054a70f36c794ebcc68252cec388f4c1 8a690b7ee89b70556d6386e3e9c7e560674fd0d2ee810ed86bff94abe41bfd21                 6401  1787953153959295985
diff --git a/.cell-installs/xdg-cache/go-build/d8/d89a30dbc551c74a49394052d976434ae19d553b20e39b819fc4e5b638201ca7-a b/.cell-installs/xdg-cache/go-build/d8/d89a30dbc551c74a49394052d976434ae19d553b20e39b819fc4e5b638201ca7-a
new file mode 100644
index 0000000..a262769
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d8/d89a30dbc551c74a49394052d976434ae19d553b20e39b819fc4e5b638201ca7-a
@@ -0,0 +1 @@
+v1 d89a30dbc551c74a49394052d976434ae19d553b20e39b819fc4e5b638201ca7 d20e2a247e7b961dae1e41d4820cd0f0ef23ed55436bd2151d6bbd307a880818                 1064  1787953154047915084
diff --git a/.cell-installs/xdg-cache/go-build/d9/d93352206bc92124f0d9f2ac5dfe24548e892159a5074413a733b962c5432dc9-d b/.cell-installs/xdg-cache/go-build/d9/d93352206bc92124f0d9f2ac5dfe24548e892159a5074413a733b962c5432dc9-d
new file mode 100644
index 0000000..975507b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d9/d93352206bc92124f0d9f2ac5dfe24548e892159a5074413a733b962c5432dc9-d
@@ -0,0 +1 @@
+./bisect.go
diff --git a/.cell-installs/xdg-cache/go-build/d9/d961178bd75d17d668c32a31434a1717a8bbcbed439cc9ac88150132dc0472d4-d b/.cell-installs/xdg-cache/go-build/d9/d961178bd75d17d668c32a31434a1717a8bbcbed439cc9ac88150132dc0472d4-d
new file mode 100644
index 0000000..1adc174
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/d9/d961178bd75d17d668c32a31434a1717a8bbcbed439cc9ac88150132dc0472d4-d differ
diff --git a/.cell-installs/xdg-cache/go-build/d9/d97991e2c5e450a371e8616d46b7db67f72f315bca16a75601c7dd7622d74257-a b/.cell-installs/xdg-cache/go-build/d9/d97991e2c5e450a371e8616d46b7db67f72f315bca16a75601c7dd7622d74257-a
new file mode 100644
index 0000000..e696d3c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/d9/d97991e2c5e450a371e8616d46b7db67f72f315bca16a75601c7dd7622d74257-a
@@ -0,0 +1 @@
+v1 d97991e2c5e450a371e8616d46b7db67f72f315bca16a75601c7dd7622d74257 f5969c583a38cf4ac3a84393f72e39ea13f36394cc4e97b4849c2b44df74181f                 1086  1787953170151430954
diff --git a/.cell-installs/xdg-cache/go-build/d9/d9cd505cd27bfd04010bd1f0247ef1d3fadd6198270a3d128470103cd217cbde-d b/.cell-installs/xdg-cache/go-build/d9/d9cd505cd27bfd04010bd1f0247ef1d3fadd6198270a3d128470103cd217cbde-d
new file mode 100644
index 0000000..a8ebbe0
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/d9/d9cd505cd27bfd04010bd1f0247ef1d3fadd6198270a3d128470103cd217cbde-d differ
diff --git a/.cell-installs/xdg-cache/go-build/d9/d9ef9079f14b3e47e5fbff492924f1a0d773d84dc132dc368d616cf83763c4d9-d b/.cell-installs/xdg-cache/go-build/d9/d9ef9079f14b3e47e5fbff492924f1a0d773d84dc132dc368d616cf83763c4d9-d
new file mode 100644
index 0000000..ef87bca
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/d9/d9ef9079f14b3e47e5fbff492924f1a0d773d84dc132dc368d616cf83763c4d9-d differ
diff --git a/.cell-installs/xdg-cache/go-build/da/da27a2c4c47c054b263dcb340bdb17831c442c8b6fddab248fa88c934d71fc0a-d b/.cell-installs/xdg-cache/go-build/da/da27a2c4c47c054b263dcb340bdb17831c442c8b6fddab248fa88c934d71fc0a-d
new file mode 100644
index 0000000..d9747c0
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/da/da27a2c4c47c054b263dcb340bdb17831c442c8b6fddab248fa88c934d71fc0a-d differ
diff --git a/.cell-installs/xdg-cache/go-build/da/da36d38f5905f277e3dbbee5fb9807708592b3a65b8832865d3f45d9885a7b24-d b/.cell-installs/xdg-cache/go-build/da/da36d38f5905f277e3dbbee5fb9807708592b3a65b8832865d3f45d9885a7b24-d
new file mode 100644
index 0000000..e345ab8
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/da/da36d38f5905f277e3dbbee5fb9807708592b3a65b8832865d3f45d9885a7b24-d differ
diff --git a/.cell-installs/xdg-cache/go-build/da/da3a93f4ddab420f19552e8fe8e82b66a02125a8f27cd8b0f9cb0a41e49f86cb-d b/.cell-installs/xdg-cache/go-build/da/da3a93f4ddab420f19552e8fe8e82b66a02125a8f27cd8b0f9cb0a41e49f86cb-d
new file mode 100644
index 0000000..64f0a0a
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/da/da3a93f4ddab420f19552e8fe8e82b66a02125a8f27cd8b0f9cb0a41e49f86cb-d differ
diff --git a/.cell-installs/xdg-cache/go-build/da/da4e55a9d54a0b36a75feb309e2ee4e2baf7b9b4d030582f3d86469415ce5b6d-d b/.cell-installs/xdg-cache/go-build/da/da4e55a9d54a0b36a75feb309e2ee4e2baf7b9b4d030582f3d86469415ce5b6d-d
new file mode 100644
index 0000000..3b11ce9
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/da/da4e55a9d54a0b36a75feb309e2ee4e2baf7b9b4d030582f3d86469415ce5b6d-d differ
diff --git a/.cell-installs/xdg-cache/go-build/da/da6c44b2002e7afb4a39ff6adf36ab31705efc3eea08d273b8cb4e4837394579-d b/.cell-installs/xdg-cache/go-build/da/da6c44b2002e7afb4a39ff6adf36ab31705efc3eea08d273b8cb4e4837394579-d
new file mode 100644
index 0000000..11e0871
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/da/da6c44b2002e7afb4a39ff6adf36ab31705efc3eea08d273b8cb4e4837394579-d differ
diff --git a/.cell-installs/xdg-cache/go-build/da/da843a3e45d26a6ecdd933ac2e2f779bae19ec28d26f184ef6e9e3eefb13f3d3-a b/.cell-installs/xdg-cache/go-build/da/da843a3e45d26a6ecdd933ac2e2f779bae19ec28d26f184ef6e9e3eefb13f3d3-a
new file mode 100644
index 0000000..4223d47
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/da/da843a3e45d26a6ecdd933ac2e2f779bae19ec28d26f184ef6e9e3eefb13f3d3-a
@@ -0,0 +1 @@
+v1 da843a3e45d26a6ecdd933ac2e2f779bae19ec28d26f184ef6e9e3eefb13f3d3 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570353593581
diff --git a/.cell-installs/xdg-cache/go-build/da/da8bce33118ec9e0a09b492630317f20de76f65f1a22bed4007d8eb0ee048990-d b/.cell-installs/xdg-cache/go-build/da/da8bce33118ec9e0a09b492630317f20de76f65f1a22bed4007d8eb0ee048990-d
new file mode 100644
index 0000000..7ffd132
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/da/da8bce33118ec9e0a09b492630317f20de76f65f1a22bed4007d8eb0ee048990-d differ
diff --git a/.cell-installs/xdg-cache/go-build/da/dac88fd70ad65a4a6560b4983838ac653e118b9d0903df9d5b1d1eceea808361-d b/.cell-installs/xdg-cache/go-build/da/dac88fd70ad65a4a6560b4983838ac653e118b9d0903df9d5b1d1eceea808361-d
new file mode 100644
index 0000000..788b291
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/da/dac88fd70ad65a4a6560b4983838ac653e118b9d0903df9d5b1d1eceea808361-d differ
diff --git a/.cell-installs/xdg-cache/go-build/db/db01e2726750f54362fa75120b88bd5f30c784d02ec533273a82b02cf592ce80-a b/.cell-installs/xdg-cache/go-build/db/db01e2726750f54362fa75120b88bd5f30c784d02ec533273a82b02cf592ce80-a
new file mode 100644
index 0000000..a84f246
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/db/db01e2726750f54362fa75120b88bd5f30c784d02ec533273a82b02cf592ce80-a
@@ -0,0 +1 @@
+v1 db01e2726750f54362fa75120b88bd5f30c784d02ec533273a82b02cf592ce80 6cb56b714a2f2243fe20536d7bb27bf123d9b380fa06f3bc867a01b09dfe43d3               182586  1787953569910731260
diff --git a/.cell-installs/xdg-cache/go-build/db/db479baf7dbb9a88b50f18ef0f7e4ebfea72109e3ff48087291e26ce02a2afad-a b/.cell-installs/xdg-cache/go-build/db/db479baf7dbb9a88b50f18ef0f7e4ebfea72109e3ff48087291e26ce02a2afad-a
new file mode 100644
index 0000000..2871a34
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/db/db479baf7dbb9a88b50f18ef0f7e4ebfea72109e3ff48087291e26ce02a2afad-a
@@ -0,0 +1 @@
+v1 db479baf7dbb9a88b50f18ef0f7e4ebfea72109e3ff48087291e26ce02a2afad eb4f0f30ddf08a9e1e7ef4ccb5b735a947a2e75455837ceb8f10778c14880c81               534028  1787953568906784036
diff --git a/.cell-installs/xdg-cache/go-build/db/dba6dac04d52d0f31f68d0f69b4bcdb86360d3945cab7321731d13367f6b767a-a b/.cell-installs/xdg-cache/go-build/db/dba6dac04d52d0f31f68d0f69b4bcdb86360d3945cab7321731d13367f6b767a-a
new file mode 100644
index 0000000..2c1910c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/db/dba6dac04d52d0f31f68d0f69b4bcdb86360d3945cab7321731d13367f6b767a-a
@@ -0,0 +1 @@
+v1 dba6dac04d52d0f31f68d0f69b4bcdb86360d3945cab7321731d13367f6b767a cf50bb48fec76bd80aa99c07f728ac78304203e7c9d41627356bb4136389efcd                44053  1787953170189906527
diff --git a/.cell-installs/xdg-cache/go-build/db/dbadd32a0e9c359c8ed1f89c7f95df6ab82bb71360481a3b3909180af531bb95-a b/.cell-installs/xdg-cache/go-build/db/dbadd32a0e9c359c8ed1f89c7f95df6ab82bb71360481a3b3909180af531bb95-a
new file mode 100644
index 0000000..3eacc0b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/db/dbadd32a0e9c359c8ed1f89c7f95df6ab82bb71360481a3b3909180af531bb95-a
@@ -0,0 +1 @@
+v1 dbadd32a0e9c359c8ed1f89c7f95df6ab82bb71360481a3b3909180af531bb95 a3ea2ddb288ddb803b0b50bd9045b6257eada13b6f5c5c9d7a84ef3e89c6a81d               559030  1787953569357204296
diff --git a/.cell-installs/xdg-cache/go-build/db/dbb1aafa85dd760a5b7dcd303d441de7b9a7cd4edff9b917b91cdc651b7e8fb8-a b/.cell-installs/xdg-cache/go-build/db/dbb1aafa85dd760a5b7dcd303d441de7b9a7cd4edff9b917b91cdc651b7e8fb8-a
new file mode 100644
index 0000000..59e6843
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/db/dbb1aafa85dd760a5b7dcd303d441de7b9a7cd4edff9b917b91cdc651b7e8fb8-a
@@ -0,0 +1 @@
+v1 dbb1aafa85dd760a5b7dcd303d441de7b9a7cd4edff9b917b91cdc651b7e8fb8 c9e606d004cc52dc1cdab23e1466ec305f9e53462c296e6eb2c3ee4595d0718f                  195  1787953570319395698
diff --git a/.cell-installs/xdg-cache/go-build/db/dbbd710b097fe764bd01a9f5fd24f4eb034219c491636772cd3f12221c37aec0-a b/.cell-installs/xdg-cache/go-build/db/dbbd710b097fe764bd01a9f5fd24f4eb034219c491636772cd3f12221c37aec0-a
new file mode 100644
index 0000000..a01257a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/db/dbbd710b097fe764bd01a9f5fd24f4eb034219c491636772cd3f12221c37aec0-a
@@ -0,0 +1 @@
+v1 dbbd710b097fe764bd01a9f5fd24f4eb034219c491636772cd3f12221c37aec0 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569319680272
diff --git a/.cell-installs/xdg-cache/go-build/db/dbc59ae57a2a731a4f0fbd14f99972d0bbed46027ece4ee51c2a231b9c7bbe60-d b/.cell-installs/xdg-cache/go-build/db/dbc59ae57a2a731a4f0fbd14f99972d0bbed46027ece4ee51c2a231b9c7bbe60-d
new file mode 100644
index 0000000..f38828b
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/db/dbc59ae57a2a731a4f0fbd14f99972d0bbed46027ece4ee51c2a231b9c7bbe60-d differ
diff --git a/.cell-installs/xdg-cache/go-build/db/dbd9a2de6e754170776ca8f14e027386b0a5233d7c43c1fbb3e19b125652717f-a b/.cell-installs/xdg-cache/go-build/db/dbd9a2de6e754170776ca8f14e027386b0a5233d7c43c1fbb3e19b125652717f-a
new file mode 100644
index 0000000..5067e04
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/db/dbd9a2de6e754170776ca8f14e027386b0a5233d7c43c1fbb3e19b125652717f-a
@@ -0,0 +1 @@
+v1 dbd9a2de6e754170776ca8f14e027386b0a5233d7c43c1fbb3e19b125652717f 289827c8a84c01c37b743d07314f5c26249d38578de6165d94dd474ccbfe81fd                  349  1787953153948828053
diff --git a/.cell-installs/xdg-cache/go-build/dc/dc4f53db333b14f42c36d050e677a1187b5602f0140c716dabdf6d67a3a69a46-a b/.cell-installs/xdg-cache/go-build/dc/dc4f53db333b14f42c36d050e677a1187b5602f0140c716dabdf6d67a3a69a46-a
new file mode 100644
index 0000000..6f9391c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/dc/dc4f53db333b14f42c36d050e677a1187b5602f0140c716dabdf6d67a3a69a46-a
@@ -0,0 +1 @@
+v1 dc4f53db333b14f42c36d050e677a1187b5602f0140c716dabdf6d67a3a69a46 2e452fe330d6b88e5eede315d867f3ad38c5188f98a8481b79ed5d7e8685188d                 1346  1787953771565157679
diff --git a/.cell-installs/xdg-cache/go-build/dc/dc8ad309136b5d3a2c2b46978a599845afd59e29aa828f40b8df26262cc6df40-d b/.cell-installs/xdg-cache/go-build/dc/dc8ad309136b5d3a2c2b46978a599845afd59e29aa828f40b8df26262cc6df40-d
new file mode 100644
index 0000000..3bb3fae
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/dc/dc8ad309136b5d3a2c2b46978a599845afd59e29aa828f40b8df26262cc6df40-d differ
diff --git a/.cell-installs/xdg-cache/go-build/dd/dd77ac134757c1ff8fd009c00eb07bd7e4b5ad3c47eab27786ce6446759bfca4-a b/.cell-installs/xdg-cache/go-build/dd/dd77ac134757c1ff8fd009c00eb07bd7e4b5ad3c47eab27786ce6446759bfca4-a
new file mode 100644
index 0000000..fb3bfd7
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/dd/dd77ac134757c1ff8fd009c00eb07bd7e4b5ad3c47eab27786ce6446759bfca4-a
@@ -0,0 +1 @@
+v1 dd77ac134757c1ff8fd009c00eb07bd7e4b5ad3c47eab27786ce6446759bfca4 f86e620c0dc84ffaf935f4db9fa4bc3db70fed7ebaf4b49831d330db0f7de1af                 1175  1787953170153010882
diff --git a/.cell-installs/xdg-cache/go-build/dd/dd8c43c6b8f89dbc612d51863f8384ea050fbff39963779176e519bae3b6371e-a b/.cell-installs/xdg-cache/go-build/dd/dd8c43c6b8f89dbc612d51863f8384ea050fbff39963779176e519bae3b6371e-a
new file mode 100644
index 0000000..1e5dc3c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/dd/dd8c43c6b8f89dbc612d51863f8384ea050fbff39963779176e519bae3b6371e-a
@@ -0,0 +1 @@
+v1 dd8c43c6b8f89dbc612d51863f8384ea050fbff39963779176e519bae3b6371e e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569908182186
diff --git a/.cell-installs/xdg-cache/go-build/dd/ddb616992acefd8bc934335fb461484f6806fae23ea082fec2e04d6da4696cec-a b/.cell-installs/xdg-cache/go-build/dd/ddb616992acefd8bc934335fb461484f6806fae23ea082fec2e04d6da4696cec-a
new file mode 100644
index 0000000..6cb593b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/dd/ddb616992acefd8bc934335fb461484f6806fae23ea082fec2e04d6da4696cec-a
@@ -0,0 +1 @@
+v1 ddb616992acefd8bc934335fb461484f6806fae23ea082fec2e04d6da4696cec 196bcb8298ec68e9fd730bcd530179198ad0bb5a00c940141fb400f951b3cdc8                  571  1787953771524842328
diff --git a/.cell-installs/xdg-cache/go-build/dd/ddf370b7b78c5439c3c007e86546851555eaf739cc0160b4bc6686ac93d3e26a-d b/.cell-installs/xdg-cache/go-build/dd/ddf370b7b78c5439c3c007e86546851555eaf739cc0160b4bc6686ac93d3e26a-d
new file mode 100644
index 0000000..4f75441
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/dd/ddf370b7b78c5439c3c007e86546851555eaf739cc0160b4bc6686ac93d3e26a-d
@@ -0,0 +1,3 @@
+./buffer.go
+./bytes.go
+./reader.go
diff --git a/.cell-installs/xdg-cache/go-build/de/de346962987804bd36dacb657cf4b70440956d8ae1f53f941e305a3cfc06e7ba-d b/.cell-installs/xdg-cache/go-build/de/de346962987804bd36dacb657cf4b70440956d8ae1f53f941e305a3cfc06e7ba-d
new file mode 100644
index 0000000..437f015
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/de/de346962987804bd36dacb657cf4b70440956d8ae1f53f941e305a3cfc06e7ba-d differ
diff --git a/.cell-installs/xdg-cache/go-build/de/de4ab6ee7434df1a596c7fad60148ddb9aace2d98461267a8bdd91679f7e7192-d b/.cell-installs/xdg-cache/go-build/de/de4ab6ee7434df1a596c7fad60148ddb9aace2d98461267a8bdd91679f7e7192-d
new file mode 100644
index 0000000..de7c9f1
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/de/de4ab6ee7434df1a596c7fad60148ddb9aace2d98461267a8bdd91679f7e7192-d differ
diff --git a/.cell-installs/xdg-cache/go-build/de/de8028b6f1a7f4238222d95ecb8587390d751ba98d2b512a9a4437ec3c73d506-d b/.cell-installs/xdg-cache/go-build/de/de8028b6f1a7f4238222d95ecb8587390d751ba98d2b512a9a4437ec3c73d506-d
new file mode 100644
index 0000000..500d648
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/de/de8028b6f1a7f4238222d95ecb8587390d751ba98d2b512a9a4437ec3c73d506-d differ
diff --git a/.cell-installs/xdg-cache/go-build/df/df2fdb2903a55a6821fb7d5bf7a8058268c7e5af00e4695844200996775f86e4-a b/.cell-installs/xdg-cache/go-build/df/df2fdb2903a55a6821fb7d5bf7a8058268c7e5af00e4695844200996775f86e4-a
new file mode 100644
index 0000000..75ca819
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/df/df2fdb2903a55a6821fb7d5bf7a8058268c7e5af00e4695844200996775f86e4-a
@@ -0,0 +1 @@
+v1 df2fdb2903a55a6821fb7d5bf7a8058268c7e5af00e4695844200996775f86e4 104702ac22f0c564f700f00c6487283866ecece0443ea799bdcc1d5355d9115e                 1150  1787953154048227598
diff --git a/.cell-installs/xdg-cache/go-build/df/dfb031a35c25045a77907df28cabe51daf13f4baca430491a1d1fcc84248776a-a b/.cell-installs/xdg-cache/go-build/df/dfb031a35c25045a77907df28cabe51daf13f4baca430491a1d1fcc84248776a-a
new file mode 100644
index 0000000..7b3d5b5
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/df/dfb031a35c25045a77907df28cabe51daf13f4baca430491a1d1fcc84248776a-a
@@ -0,0 +1 @@
+v1 dfb031a35c25045a77907df28cabe51daf13f4baca430491a1d1fcc84248776a 5053a2e9eab5ebe8949421fa803383d4c1ecc84998623948d2a07235a7f29069                 2310  1787953153944110865
diff --git a/.cell-installs/xdg-cache/go-build/df/dffc4c0d8514676e1f55e0ec006adf87945eb7fbf3ebb2e63d3f7f49c0875500-a b/.cell-installs/xdg-cache/go-build/df/dffc4c0d8514676e1f55e0ec006adf87945eb7fbf3ebb2e63d3f7f49c0875500-a
new file mode 100644
index 0000000..6ea0cce
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/df/dffc4c0d8514676e1f55e0ec006adf87945eb7fbf3ebb2e63d3f7f49c0875500-a
@@ -0,0 +1 @@
+v1 dffc4c0d8514676e1f55e0ec006adf87945eb7fbf3ebb2e63d3f7f49c0875500 132645e69702a38b40a3d04333dc2f3261cddb5ab6092f9e1cd6077181447049                   26  1787953568823462189
diff --git a/.cell-installs/xdg-cache/go-build/df/dffced44a9fba151a6c99f12e2feac64b5e53acc45fe9fda88ceb4534cfc0ae4-d b/.cell-installs/xdg-cache/go-build/df/dffced44a9fba151a6c99f12e2feac64b5e53acc45fe9fda88ceb4534cfc0ae4-d
new file mode 100644
index 0000000..eadf521
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/df/dffced44a9fba151a6c99f12e2feac64b5e53acc45fe9fda88ceb4534cfc0ae4-d differ
diff --git a/.cell-installs/xdg-cache/go-build/e0/e00dff66b3d7966c2cd42b6d4d54355041aab7fae14679a4dd6f8cb178b3e42f-a b/.cell-installs/xdg-cache/go-build/e0/e00dff66b3d7966c2cd42b6d4d54355041aab7fae14679a4dd6f8cb178b3e42f-a
new file mode 100644
index 0000000..2ac988b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e0/e00dff66b3d7966c2cd42b6d4d54355041aab7fae14679a4dd6f8cb178b3e42f-a
@@ -0,0 +1 @@
+v1 e00dff66b3d7966c2cd42b6d4d54355041aab7fae14679a4dd6f8cb178b3e42f 8011e9c53622e4ccba7d311ba870ce1ae1444a4269e0abb0ba08e9582806ae4f                   23  1787953569868518843
diff --git a/.cell-installs/xdg-cache/go-build/e0/e014b97f5fa47de4c02e87b154c2e3013e36986dc1ccc7a45cd0287691d34c97-a b/.cell-installs/xdg-cache/go-build/e0/e014b97f5fa47de4c02e87b154c2e3013e36986dc1ccc7a45cd0287691d34c97-a
new file mode 100644
index 0000000..f4fc2f7
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e0/e014b97f5fa47de4c02e87b154c2e3013e36986dc1ccc7a45cd0287691d34c97-a
@@ -0,0 +1 @@
+v1 e014b97f5fa47de4c02e87b154c2e3013e36986dc1ccc7a45cd0287691d34c97 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568895853736
diff --git a/.cell-installs/xdg-cache/go-build/e0/e036101109ed42b7f45be0fc3591a6418fcf1ad0a3503b3325e5aa0196086e8f-a b/.cell-installs/xdg-cache/go-build/e0/e036101109ed42b7f45be0fc3591a6418fcf1ad0a3503b3325e5aa0196086e8f-a
new file mode 100644
index 0000000..e654b6f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e0/e036101109ed42b7f45be0fc3591a6418fcf1ad0a3503b3325e5aa0196086e8f-a
@@ -0,0 +1 @@
+v1 e036101109ed42b7f45be0fc3591a6418fcf1ad0a3503b3325e5aa0196086e8f 69a8a35487589134e88fae6e9944960fe39e95e6e490fe2cb639ab48aaa35094                   10  1787953569821200326
diff --git a/.cell-installs/xdg-cache/go-build/e0/e0597462217ba0f0fd7b250ed598e0b7211cd38ba47be600ceceba75534a8471-a b/.cell-installs/xdg-cache/go-build/e0/e0597462217ba0f0fd7b250ed598e0b7211cd38ba47be600ceceba75534a8471-a
new file mode 100644
index 0000000..bfb546b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e0/e0597462217ba0f0fd7b250ed598e0b7211cd38ba47be600ceceba75534a8471-a
@@ -0,0 +1 @@
+v1 e0597462217ba0f0fd7b250ed598e0b7211cd38ba47be600ceceba75534a8471 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569721736378
diff --git a/.cell-installs/xdg-cache/go-build/e0/e0b533f99b789d6397226d89fb0dc8bb81b37ffed8dc3d5ac70d088f6c0242f7-a b/.cell-installs/xdg-cache/go-build/e0/e0b533f99b789d6397226d89fb0dc8bb81b37ffed8dc3d5ac70d088f6c0242f7-a
new file mode 100644
index 0000000..cc9fe83
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e0/e0b533f99b789d6397226d89fb0dc8bb81b37ffed8dc3d5ac70d088f6c0242f7-a
@@ -0,0 +1 @@
+v1 e0b533f99b789d6397226d89fb0dc8bb81b37ffed8dc3d5ac70d088f6c0242f7 71663442f4be87697bed0ef6a6f5d62aee55e546791a73518a4575fa44250aa5                 1740  1787953153942469288
diff --git a/.cell-installs/xdg-cache/go-build/e0/e0f9701841499e4caed1307e4d993c0f126ff67fe097c2c8b0d422b6bc97e558-a b/.cell-installs/xdg-cache/go-build/e0/e0f9701841499e4caed1307e4d993c0f126ff67fe097c2c8b0d422b6bc97e558-a
new file mode 100644
index 0000000..394b80d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e0/e0f9701841499e4caed1307e4d993c0f126ff67fe097c2c8b0d422b6bc97e558-a
@@ -0,0 +1 @@
+v1 e0f9701841499e4caed1307e4d993c0f126ff67fe097c2c8b0d422b6bc97e558 4b4f9a0534b1fb3049a4febd92ed872477f39fff75c2216c672fe9eed912d400                 6288  1787953568984069570
diff --git a/.cell-installs/xdg-cache/go-build/e1/e14aa7c805b7c94b68756b43fc5a6f520f1bee8971efa17d600f562b9b1f06b5-a b/.cell-installs/xdg-cache/go-build/e1/e14aa7c805b7c94b68756b43fc5a6f520f1bee8971efa17d600f562b9b1f06b5-a
new file mode 100644
index 0000000..8f39950
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e1/e14aa7c805b7c94b68756b43fc5a6f520f1bee8971efa17d600f562b9b1f06b5-a
@@ -0,0 +1 @@
+v1 e14aa7c805b7c94b68756b43fc5a6f520f1bee8971efa17d600f562b9b1f06b5 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568852825048
diff --git a/.cell-installs/xdg-cache/go-build/e1/e1631708fb78923ed16d97394a7beb29aa18e4688e3f730fbf8eb654b18dae48-a b/.cell-installs/xdg-cache/go-build/e1/e1631708fb78923ed16d97394a7beb29aa18e4688e3f730fbf8eb654b18dae48-a
new file mode 100644
index 0000000..d1d3608
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e1/e1631708fb78923ed16d97394a7beb29aa18e4688e3f730fbf8eb654b18dae48-a
@@ -0,0 +1 @@
+v1 e1631708fb78923ed16d97394a7beb29aa18e4688e3f730fbf8eb654b18dae48 913b872653a2f7cb8dccac9a3bc863733908fae88a227f72506fb461aa5d8a19                 3672  1787953170164875312
diff --git a/.cell-installs/xdg-cache/go-build/e1/e1cdd23c9f7eb506ae94b8ee061010759f0d5afd514322827b4d71bad7ff5f9a-d b/.cell-installs/xdg-cache/go-build/e1/e1cdd23c9f7eb506ae94b8ee061010759f0d5afd514322827b4d71bad7ff5f9a-d
new file mode 100644
index 0000000..ef3b3e8
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/e1/e1cdd23c9f7eb506ae94b8ee061010759f0d5afd514322827b4d71bad7ff5f9a-d differ
diff --git a/.cell-installs/xdg-cache/go-build/e1/e1f4928a75355573e92499d4ab842fde5cdc23fe7dc03967d6a4ca5c634ab18b-d b/.cell-installs/xdg-cache/go-build/e1/e1f4928a75355573e92499d4ab842fde5cdc23fe7dc03967d6a4ca5c634ab18b-d
new file mode 100644
index 0000000..62d4583
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e1/e1f4928a75355573e92499d4ab842fde5cdc23fe7dc03967d6a4ca5c634ab18b-d
@@ -0,0 +1,2 @@
+./cpuinfo_linux.go
+./sysinfo.go
diff --git a/.cell-installs/xdg-cache/go-build/e2/e26087bc3f3d31e01c82cf998b6ed2bff08de0bc432a6a6f6002a5416119a2ba-a b/.cell-installs/xdg-cache/go-build/e2/e26087bc3f3d31e01c82cf998b6ed2bff08de0bc432a6a6f6002a5416119a2ba-a
new file mode 100644
index 0000000..620be4e
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e2/e26087bc3f3d31e01c82cf998b6ed2bff08de0bc432a6a6f6002a5416119a2ba-a
@@ -0,0 +1 @@
+v1 e26087bc3f3d31e01c82cf998b6ed2bff08de0bc432a6a6f6002a5416119a2ba e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569918170442
diff --git a/.cell-installs/xdg-cache/go-build/e2/e2a3a654f38558dd07ead8367e44fb55445c89bf000d6a2b1c7ec462384fa2bf-d b/.cell-installs/xdg-cache/go-build/e2/e2a3a654f38558dd07ead8367e44fb55445c89bf000d6a2b1c7ec462384fa2bf-d
new file mode 100644
index 0000000..504deb2
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/e2/e2a3a654f38558dd07ead8367e44fb55445c89bf000d6a2b1c7ec462384fa2bf-d differ
diff --git a/.cell-installs/xdg-cache/go-build/e2/e2c91c04bba4484d729b8ad853031cfae82ac16810de67ff674c9bd13fda8408-d b/.cell-installs/xdg-cache/go-build/e2/e2c91c04bba4484d729b8ad853031cfae82ac16810de67ff674c9bd13fda8408-d
new file mode 100644
index 0000000..1b0b07d
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/e2/e2c91c04bba4484d729b8ad853031cfae82ac16810de67ff674c9bd13fda8408-d differ
diff --git a/.cell-installs/xdg-cache/go-build/e2/e2de7559fce24e738b5722bbe1974ffe139d7f4503607b6da91b74508258bd1e-a b/.cell-installs/xdg-cache/go-build/e2/e2de7559fce24e738b5722bbe1974ffe139d7f4503607b6da91b74508258bd1e-a
new file mode 100644
index 0000000..53f87b5
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e2/e2de7559fce24e738b5722bbe1974ffe139d7f4503607b6da91b74508258bd1e-a
@@ -0,0 +1 @@
+v1 e2de7559fce24e738b5722bbe1974ffe139d7f4503607b6da91b74508258bd1e 445aef4ac858ea51c41319209be0586bae34453c25d9d42f93d15af814de64e8                  618  1787953170145343487
diff --git a/.cell-installs/xdg-cache/go-build/e3/e300fb408153255ed48095df3ed13d3282d252b32f156afff0b0b01ffa31a8d6-a b/.cell-installs/xdg-cache/go-build/e3/e300fb408153255ed48095df3ed13d3282d252b32f156afff0b0b01ffa31a8d6-a
new file mode 100644
index 0000000..113cfef
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e3/e300fb408153255ed48095df3ed13d3282d252b32f156afff0b0b01ffa31a8d6-a
@@ -0,0 +1 @@
+v1 e300fb408153255ed48095df3ed13d3282d252b32f156afff0b0b01ffa31a8d6 9425e97d417a0f96d312414cf09a9637105bce01614cc9812cc657a913db1b1b                 1994  1787953153938893158
diff --git a/.cell-installs/xdg-cache/go-build/e3/e323dc777d18dc4ae61daedea46516e84ba65000e5ec9e0887b337bc321fb6a9-a b/.cell-installs/xdg-cache/go-build/e3/e323dc777d18dc4ae61daedea46516e84ba65000e5ec9e0887b337bc321fb6a9-a
new file mode 100644
index 0000000..412e758
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e3/e323dc777d18dc4ae61daedea46516e84ba65000e5ec9e0887b337bc321fb6a9-a
@@ -0,0 +1 @@
+v1 e323dc777d18dc4ae61daedea46516e84ba65000e5ec9e0887b337bc321fb6a9 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567789353076
diff --git a/.cell-installs/xdg-cache/go-build/e3/e32abf2ee1120847e9dffe170372d53207aefc72a1c5fc5bd60757c075c91d0f-d b/.cell-installs/xdg-cache/go-build/e3/e32abf2ee1120847e9dffe170372d53207aefc72a1c5fc5bd60757c075c91d0f-d
new file mode 100644
index 0000000..ff745ae
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/e3/e32abf2ee1120847e9dffe170372d53207aefc72a1c5fc5bd60757c075c91d0f-d differ
diff --git a/.cell-installs/xdg-cache/go-build/e3/e32be8a055815417910e9cf549349ba39f9244aabdc67f191a6fe6cb57625245-a b/.cell-installs/xdg-cache/go-build/e3/e32be8a055815417910e9cf549349ba39f9244aabdc67f191a6fe6cb57625245-a
new file mode 100644
index 0000000..d986f38
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e3/e32be8a055815417910e9cf549349ba39f9244aabdc67f191a6fe6cb57625245-a
@@ -0,0 +1 @@
+v1 e32be8a055815417910e9cf549349ba39f9244aabdc67f191a6fe6cb57625245 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570303781308
diff --git a/.cell-installs/xdg-cache/go-build/e3/e34ff5ae46bdb05e4ea7783595645be4ae47c0d130f09383a1b89e9ecbaa9612-a b/.cell-installs/xdg-cache/go-build/e3/e34ff5ae46bdb05e4ea7783595645be4ae47c0d130f09383a1b89e9ecbaa9612-a
new file mode 100644
index 0000000..710f13b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e3/e34ff5ae46bdb05e4ea7783595645be4ae47c0d130f09383a1b89e9ecbaa9612-a
@@ -0,0 +1 @@
+v1 e34ff5ae46bdb05e4ea7783595645be4ae47c0d130f09383a1b89e9ecbaa9612 1e1cab71c7ec26658dc2da9a9e51a78ac604a06e74e4d3f1c69d49c1a11be6d5                  133  1787953570230930901
diff --git a/.cell-installs/xdg-cache/go-build/e3/e378d30fec97c7db0c8736b4560b3127edc27bedf3f9ed080feb04aa99d7a1a3-a b/.cell-installs/xdg-cache/go-build/e3/e378d30fec97c7db0c8736b4560b3127edc27bedf3f9ed080feb04aa99d7a1a3-a
new file mode 100644
index 0000000..ff63979
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e3/e378d30fec97c7db0c8736b4560b3127edc27bedf3f9ed080feb04aa99d7a1a3-a
@@ -0,0 +1 @@
+v1 e378d30fec97c7db0c8736b4560b3127edc27bedf3f9ed080feb04aa99d7a1a3 c48aaaeb3caa91e9a641e50c3b7e0651c6d6888829eb554cb1220c9207b6fbd0              1710326  1787953568975064565
diff --git a/.cell-installs/xdg-cache/go-build/e3/e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855-d b/.cell-installs/xdg-cache/go-build/e3/e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855-d
new file mode 100644
index 0000000..e69de29
diff --git a/.cell-installs/xdg-cache/go-build/e4/e4099adf0070d71db55a2c345737309ae937aead16e67ca7dd570da03892f54f-a b/.cell-installs/xdg-cache/go-build/e4/e4099adf0070d71db55a2c345737309ae937aead16e67ca7dd570da03892f54f-a
new file mode 100644
index 0000000..e168f12
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e4/e4099adf0070d71db55a2c345737309ae937aead16e67ca7dd570da03892f54f-a
@@ -0,0 +1 @@
+v1 e4099adf0070d71db55a2c345737309ae937aead16e67ca7dd570da03892f54f e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569317788910
diff --git a/.cell-installs/xdg-cache/go-build/e4/e4b89bb69688b9ada922fd5da8d53b502f4daf2ea760bdb5dc88a1987a8ab43e-a b/.cell-installs/xdg-cache/go-build/e4/e4b89bb69688b9ada922fd5da8d53b502f4daf2ea760bdb5dc88a1987a8ab43e-a
new file mode 100644
index 0000000..8498e62
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e4/e4b89bb69688b9ada922fd5da8d53b502f4daf2ea760bdb5dc88a1987a8ab43e-a
@@ -0,0 +1 @@
+v1 e4b89bb69688b9ada922fd5da8d53b502f4daf2ea760bdb5dc88a1987a8ab43e cbca567be2e044f31d62c5c4202d38d2ab718a6788946ce1edf6d6ae5e2d45be               113038  1787953569939075453
diff --git a/.cell-installs/xdg-cache/go-build/e4/e4cb5c6ee6bcccd72c1040551c01341e9a7656f3c673c366cbb373be3d7cca5f-a b/.cell-installs/xdg-cache/go-build/e4/e4cb5c6ee6bcccd72c1040551c01341e9a7656f3c673c366cbb373be3d7cca5f-a
new file mode 100644
index 0000000..0950fd6
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e4/e4cb5c6ee6bcccd72c1040551c01341e9a7656f3c673c366cbb373be3d7cca5f-a
@@ -0,0 +1 @@
+v1 e4cb5c6ee6bcccd72c1040551c01341e9a7656f3c673c366cbb373be3d7cca5f f416aff38047cab648129e9819c6527a9ad2fec54a65692a965e29b24b2d8bc9                  276  1787953569557038730
diff --git a/.cell-installs/xdg-cache/go-build/e4/e4fffda4e190895eee0531c5a294004a108259c8eb40c339d20bb497954fa20b-a b/.cell-installs/xdg-cache/go-build/e4/e4fffda4e190895eee0531c5a294004a108259c8eb40c339d20bb497954fa20b-a
new file mode 100644
index 0000000..24a9415
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e4/e4fffda4e190895eee0531c5a294004a108259c8eb40c339d20bb497954fa20b-a
@@ -0,0 +1 @@
+v1 e4fffda4e190895eee0531c5a294004a108259c8eb40c339d20bb497954fa20b e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569579286914
diff --git a/.cell-installs/xdg-cache/go-build/e5/e51d6ea491ca45ca259f2fe86e57cc34007b4c5e9a3d79c39122ca677bd32939-a b/.cell-installs/xdg-cache/go-build/e5/e51d6ea491ca45ca259f2fe86e57cc34007b4c5e9a3d79c39122ca677bd32939-a
new file mode 100644
index 0000000..2d9a700
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e5/e51d6ea491ca45ca259f2fe86e57cc34007b4c5e9a3d79c39122ca677bd32939-a
@@ -0,0 +1 @@
+v1 e51d6ea491ca45ca259f2fe86e57cc34007b4c5e9a3d79c39122ca677bd32939 2c0bab44b84efa95c080ec8c20e83fdaec7a95659669932c54fe6f729d700e79                 3142  1787953170149206335
diff --git a/.cell-installs/xdg-cache/go-build/e5/e53e2d897c41072c18348ec6710ea625ec140e2d755baecd7168f06eb3f99c87-a b/.cell-installs/xdg-cache/go-build/e5/e53e2d897c41072c18348ec6710ea625ec140e2d755baecd7168f06eb3f99c87-a
new file mode 100644
index 0000000..f2202ea
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e5/e53e2d897c41072c18348ec6710ea625ec140e2d755baecd7168f06eb3f99c87-a
@@ -0,0 +1 @@
+v1 e53e2d897c41072c18348ec6710ea625ec140e2d755baecd7168f06eb3f99c87 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568737021136
diff --git a/.cell-installs/xdg-cache/go-build/e5/e579be44c2c2eda129c992f26f35827d13bba9f9d7fa86d04cb438bcc2b7a74c-a b/.cell-installs/xdg-cache/go-build/e5/e579be44c2c2eda129c992f26f35827d13bba9f9d7fa86d04cb438bcc2b7a74c-a
new file mode 100644
index 0000000..b605657
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e5/e579be44c2c2eda129c992f26f35827d13bba9f9d7fa86d04cb438bcc2b7a74c-a
@@ -0,0 +1 @@
+v1 e579be44c2c2eda129c992f26f35827d13bba9f9d7fa86d04cb438bcc2b7a74c 6375748d9557a551364d25f7bcb3d2f22aa8f001270937221449c32bbcdde43f                  342  1787953170161660833
diff --git a/.cell-installs/xdg-cache/go-build/e5/e586146a93984192a604373b3f651622d7c14c44c4efd04faa7e28ed701615db-a b/.cell-installs/xdg-cache/go-build/e5/e586146a93984192a604373b3f651622d7c14c44c4efd04faa7e28ed701615db-a
new file mode 100644
index 0000000..d640f27
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e5/e586146a93984192a604373b3f651622d7c14c44c4efd04faa7e28ed701615db-a
@@ -0,0 +1 @@
+v1 e586146a93984192a604373b3f651622d7c14c44c4efd04faa7e28ed701615db e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569939527105
diff --git a/.cell-installs/xdg-cache/go-build/e5/e5e9b3f8cfe4e54efed65f6835938bcc466c9bdf23014affb5a807cc40ae4e03-a b/.cell-installs/xdg-cache/go-build/e5/e5e9b3f8cfe4e54efed65f6835938bcc466c9bdf23014affb5a807cc40ae4e03-a
new file mode 100644
index 0000000..30bc63c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e5/e5e9b3f8cfe4e54efed65f6835938bcc466c9bdf23014affb5a807cc40ae4e03-a
@@ -0,0 +1 @@
+v1 e5e9b3f8cfe4e54efed65f6835938bcc466c9bdf23014affb5a807cc40ae4e03 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569315872335
diff --git a/.cell-installs/xdg-cache/go-build/e5/e5f15fe12f731081d386b881666b2522b3c4aec4e4b6cb65b6e580aaf8754a5a-a b/.cell-installs/xdg-cache/go-build/e5/e5f15fe12f731081d386b881666b2522b3c4aec4e4b6cb65b6e580aaf8754a5a-a
new file mode 100644
index 0000000..b380a6f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e5/e5f15fe12f731081d386b881666b2522b3c4aec4e4b6cb65b6e580aaf8754a5a-a
@@ -0,0 +1 @@
+v1 e5f15fe12f731081d386b881666b2522b3c4aec4e4b6cb65b6e580aaf8754a5a a081422f09c698a34f06d03aa7162770640c6b09b55f5af1662148d896290ffb                 2971  1787953153944220211
diff --git a/.cell-installs/xdg-cache/go-build/e5/e5f4a6105458529a6aaff7346201a02d382c0bf134b98136ef400cefd8ac7b07-a b/.cell-installs/xdg-cache/go-build/e5/e5f4a6105458529a6aaff7346201a02d382c0bf134b98136ef400cefd8ac7b07-a
new file mode 100644
index 0000000..8babe85
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e5/e5f4a6105458529a6aaff7346201a02d382c0bf134b98136ef400cefd8ac7b07-a
@@ -0,0 +1 @@
+v1 e5f4a6105458529a6aaff7346201a02d382c0bf134b98136ef400cefd8ac7b07 c006f6b98f8b8679d49ee133387aaf81c465084a63cdc9939d5febb2fe105429                  507  1787953170169279585
diff --git a/.cell-installs/xdg-cache/go-build/e6/e619c61c469dd9fae2a5b01142f27f32632b38b877121eb3c910150ae4defd4d-d b/.cell-installs/xdg-cache/go-build/e6/e619c61c469dd9fae2a5b01142f27f32632b38b877121eb3c910150ae4defd4d-d
new file mode 100644
index 0000000..6e33120
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/e6/e619c61c469dd9fae2a5b01142f27f32632b38b877121eb3c910150ae4defd4d-d differ
diff --git a/.cell-installs/xdg-cache/go-build/e6/e65bd570e174ea3484a4bc6dbac412aabc18e58f805723545b71908259d36ea5-d b/.cell-installs/xdg-cache/go-build/e6/e65bd570e174ea3484a4bc6dbac412aabc18e58f805723545b71908259d36ea5-d
new file mode 100644
index 0000000..a84e8e8
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/e6/e65bd570e174ea3484a4bc6dbac412aabc18e58f805723545b71908259d36ea5-d differ
diff --git a/.cell-installs/xdg-cache/go-build/e6/e6b34a14b1987225409832aa5f8084e31ccd9a6556bb8558e5e134ef47a8c44e-a b/.cell-installs/xdg-cache/go-build/e6/e6b34a14b1987225409832aa5f8084e31ccd9a6556bb8558e5e134ef47a8c44e-a
new file mode 100644
index 0000000..2376d8a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e6/e6b34a14b1987225409832aa5f8084e31ccd9a6556bb8558e5e134ef47a8c44e-a
@@ -0,0 +1 @@
+v1 e6b34a14b1987225409832aa5f8084e31ccd9a6556bb8558e5e134ef47a8c44e 710559d46f53e97d75a5427b0a28b0526ca3e8c7c7ba96839cf91399d61169b7              1116922  1787953569093557984
diff --git a/.cell-installs/xdg-cache/go-build/e6/e6ca2ff2127b18a3433da89c097372c108b814f87e9fabca861d88fc2fa8193c-d b/.cell-installs/xdg-cache/go-build/e6/e6ca2ff2127b18a3433da89c097372c108b814f87e9fabca861d88fc2fa8193c-d
new file mode 100644
index 0000000..7507673
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/e6/e6ca2ff2127b18a3433da89c097372c108b814f87e9fabca861d88fc2fa8193c-d differ
diff --git a/.cell-installs/xdg-cache/go-build/e7/e74f792fc4415e4d124a5c6efc79992f9dfa2e4382a52b82b0ef2f8be163bb47-a b/.cell-installs/xdg-cache/go-build/e7/e74f792fc4415e4d124a5c6efc79992f9dfa2e4382a52b82b0ef2f8be163bb47-a
new file mode 100644
index 0000000..f392f37
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e7/e74f792fc4415e4d124a5c6efc79992f9dfa2e4382a52b82b0ef2f8be163bb47-a
@@ -0,0 +1 @@
+v1 e74f792fc4415e4d124a5c6efc79992f9dfa2e4382a52b82b0ef2f8be163bb47 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570209809182
diff --git a/.cell-installs/xdg-cache/go-build/e7/e7d216b132e1ce900567927f805a29cb3351246eea203b4b832fb29c684057b9-a b/.cell-installs/xdg-cache/go-build/e7/e7d216b132e1ce900567927f805a29cb3351246eea203b4b832fb29c684057b9-a
new file mode 100644
index 0000000..1f74136
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e7/e7d216b132e1ce900567927f805a29cb3351246eea203b4b832fb29c684057b9-a
@@ -0,0 +1 @@
+v1 e7d216b132e1ce900567927f805a29cb3351246eea203b4b832fb29c684057b9 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569337722733
diff --git a/.cell-installs/xdg-cache/go-build/e8/e84c82c8ac6c7f5a0a08744979078e77b44ebdd1d855963def9e97ce70ba6bd7-d b/.cell-installs/xdg-cache/go-build/e8/e84c82c8ac6c7f5a0a08744979078e77b44ebdd1d855963def9e97ce70ba6bd7-d
new file mode 100644
index 0000000..16cb95a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e8/e84c82c8ac6c7f5a0a08744979078e77b44ebdd1d855963def9e97ce70ba6bd7-d
@@ -0,0 +1,11 @@
+./elf.go
+./label.go
+./map.go
+./pe.go
+./pprof.go
+./pprof_rusage.go
+./proto.go
+./proto_other.go
+./protobuf.go
+./protomem.go
+./runtime.go
diff --git a/.cell-installs/xdg-cache/go-build/e8/e86af54ff100e0a34a7be3d786ca322d4fa0db1a8c0dca6c5b08a3cc2b0dc19b-d b/.cell-installs/xdg-cache/go-build/e8/e86af54ff100e0a34a7be3d786ca322d4fa0db1a8c0dca6c5b08a3cc2b0dc19b-d
new file mode 100644
index 0000000..1b32080
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/e8/e86af54ff100e0a34a7be3d786ca322d4fa0db1a8c0dca6c5b08a3cc2b0dc19b-d differ
diff --git a/.cell-installs/xdg-cache/go-build/e8/e883a684e08cc1337468d79f6e48914f48aef3364f2c41bc9232fa20a849a656-a b/.cell-installs/xdg-cache/go-build/e8/e883a684e08cc1337468d79f6e48914f48aef3364f2c41bc9232fa20a849a656-a
new file mode 100644
index 0000000..4481dcd
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e8/e883a684e08cc1337468d79f6e48914f48aef3364f2c41bc9232fa20a849a656-a
@@ -0,0 +1 @@
+v1 e883a684e08cc1337468d79f6e48914f48aef3364f2c41bc9232fa20a849a656 6cdd4241dc286da77c5143ffd44842f54fca37f86c5d522de0de93b06d1e26f0               584866  1787953567877373372
diff --git a/.cell-installs/xdg-cache/go-build/e8/e8a9826224983006be9b859d3b648df388afa611b65ece6a2ce39f30f569c098-d b/.cell-installs/xdg-cache/go-build/e8/e8a9826224983006be9b859d3b648df388afa611b65ece6a2ce39f30f569c098-d
new file mode 100644
index 0000000..ec01857
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/e8/e8a9826224983006be9b859d3b648df388afa611b65ece6a2ce39f30f569c098-d differ
diff --git a/.cell-installs/xdg-cache/go-build/e8/e8f03632c221909d06379748b49e04bda1c691a8419330d3c81fa41d849e56d7-a b/.cell-installs/xdg-cache/go-build/e8/e8f03632c221909d06379748b49e04bda1c691a8419330d3c81fa41d849e56d7-a
new file mode 100644
index 0000000..31ed249
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/e8/e8f03632c221909d06379748b49e04bda1c691a8419330d3c81fa41d849e56d7-a
@@ -0,0 +1 @@
+v1 e8f03632c221909d06379748b49e04bda1c691a8419330d3c81fa41d849e56d7 dffced44a9fba151a6c99f12e2feac64b5e53acc45fe9fda88ceb4534cfc0ae4                 1150  1787953170161131977
diff --git a/.cell-installs/xdg-cache/go-build/e9/e9360993b5ed79d246b6e214268ef1803c5b7113b6f71b5c741cab881c66271e-d b/.cell-installs/xdg-cache/go-build/e9/e9360993b5ed79d246b6e214268ef1803c5b7113b6f71b5c741cab881c66271e-d
new file mode 100644
index 0000000..6b50462
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/e9/e9360993b5ed79d246b6e214268ef1803c5b7113b6f71b5c741cab881c66271e-d differ
diff --git a/.cell-installs/xdg-cache/go-build/e9/e938a758c5f73fd4cc18f356a0551b65fb020bb5b71b0eebe654e2f9f4160d39-d b/.cell-installs/xdg-cache/go-build/e9/e938a758c5f73fd4cc18f356a0551b65fb020bb5b71b0eebe654e2f9f4160d39-d
new file mode 100644
index 0000000..188a1a5
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/e9/e938a758c5f73fd4cc18f356a0551b65fb020bb5b71b0eebe654e2f9f4160d39-d differ
diff --git a/.cell-installs/xdg-cache/go-build/e9/e9b258c07795d46311fe15ade947865f3b41d08453c938ead71e3b2227bc7e79-d b/.cell-installs/xdg-cache/go-build/e9/e9b258c07795d46311fe15ade947865f3b41d08453c938ead71e3b2227bc7e79-d
new file mode 100644
index 0000000..8e9efc5
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/e9/e9b258c07795d46311fe15ade947865f3b41d08453c938ead71e3b2227bc7e79-d differ
diff --git a/.cell-installs/xdg-cache/go-build/ea/ea18afcffb38626dce7d82c15d7dceb49fed15ff719140ca00a68b4e48d5e7ef-a b/.cell-installs/xdg-cache/go-build/ea/ea18afcffb38626dce7d82c15d7dceb49fed15ff719140ca00a68b4e48d5e7ef-a
new file mode 100644
index 0000000..6f7e389
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ea/ea18afcffb38626dce7d82c15d7dceb49fed15ff719140ca00a68b4e48d5e7ef-a
@@ -0,0 +1 @@
+v1 ea18afcffb38626dce7d82c15d7dceb49fed15ff719140ca00a68b4e48d5e7ef e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569915514307
diff --git a/.cell-installs/xdg-cache/go-build/eb/eb4f0f30ddf08a9e1e7ef4ccb5b735a947a2e75455837ceb8f10778c14880c81-d b/.cell-installs/xdg-cache/go-build/eb/eb4f0f30ddf08a9e1e7ef4ccb5b735a947a2e75455837ceb8f10778c14880c81-d
new file mode 100644
index 0000000..7f16019
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/eb/eb4f0f30ddf08a9e1e7ef4ccb5b735a947a2e75455837ceb8f10778c14880c81-d differ
diff --git a/.cell-installs/xdg-cache/go-build/eb/eb8042399142adfc196405e3d94b1ad486f8cd5d2ab9722f494e90874eb003fd-a b/.cell-installs/xdg-cache/go-build/eb/eb8042399142adfc196405e3d94b1ad486f8cd5d2ab9722f494e90874eb003fd-a
new file mode 100644
index 0000000..d1809cd
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/eb/eb8042399142adfc196405e3d94b1ad486f8cd5d2ab9722f494e90874eb003fd-a
@@ -0,0 +1 @@
+v1 eb8042399142adfc196405e3d94b1ad486f8cd5d2ab9722f494e90874eb003fd e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570182110539
diff --git a/.cell-installs/xdg-cache/go-build/eb/ebc608743758e879c3f560d024471ea55a11abb749e0611efebcefc11fc1d663-d b/.cell-installs/xdg-cache/go-build/eb/ebc608743758e879c3f560d024471ea55a11abb749e0611efebcefc11fc1d663-d
new file mode 100644
index 0000000..e1aa89f
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/eb/ebc608743758e879c3f560d024471ea55a11abb749e0611efebcefc11fc1d663-d differ
diff --git a/.cell-installs/xdg-cache/go-build/eb/ebcad891fdc35222652d1b58366ab702a46ef9a928e3a8cc91efd8edc344a150-a b/.cell-installs/xdg-cache/go-build/eb/ebcad891fdc35222652d1b58366ab702a46ef9a928e3a8cc91efd8edc344a150-a
new file mode 100644
index 0000000..dabbbd8
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/eb/ebcad891fdc35222652d1b58366ab702a46ef9a928e3a8cc91efd8edc344a150-a
@@ -0,0 +1 @@
+v1 ebcad891fdc35222652d1b58366ab702a46ef9a928e3a8cc91efd8edc344a150 c33d39baad75170fdde723be2e3432b923aa3c6e57b71aa2b20bb54a3e2864a5                  430  1787953771566785051
diff --git a/.cell-installs/xdg-cache/go-build/eb/ebede7e3b7408a70552da202406802d584ccf9b24fa6fba7f4e47d7b77bd03a4-a b/.cell-installs/xdg-cache/go-build/eb/ebede7e3b7408a70552da202406802d584ccf9b24fa6fba7f4e47d7b77bd03a4-a
new file mode 100644
index 0000000..1086741
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/eb/ebede7e3b7408a70552da202406802d584ccf9b24fa6fba7f4e47d7b77bd03a4-a
@@ -0,0 +1 @@
+v1 ebede7e3b7408a70552da202406802d584ccf9b24fa6fba7f4e47d7b77bd03a4 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568855586330
diff --git a/.cell-installs/xdg-cache/go-build/ec/ec7ccb27226589488dd7047bdf55a06b759b9cd2dcd5a2cfddaa2e251e71e396-a b/.cell-installs/xdg-cache/go-build/ec/ec7ccb27226589488dd7047bdf55a06b759b9cd2dcd5a2cfddaa2e251e71e396-a
new file mode 100644
index 0000000..26bf2f1
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ec/ec7ccb27226589488dd7047bdf55a06b759b9cd2dcd5a2cfddaa2e251e71e396-a
@@ -0,0 +1 @@
+v1 ec7ccb27226589488dd7047bdf55a06b759b9cd2dcd5a2cfddaa2e251e71e396 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568971491509
diff --git a/.cell-installs/xdg-cache/go-build/ec/ec8b2a49f54fb0eee768424e6a1608bf9da231374998ec8966cfe9a0c00eeffe-a b/.cell-installs/xdg-cache/go-build/ec/ec8b2a49f54fb0eee768424e6a1608bf9da231374998ec8966cfe9a0c00eeffe-a
new file mode 100644
index 0000000..6e01856
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ec/ec8b2a49f54fb0eee768424e6a1608bf9da231374998ec8966cfe9a0c00eeffe-a
@@ -0,0 +1 @@
+v1 ec8b2a49f54fb0eee768424e6a1608bf9da231374998ec8966cfe9a0c00eeffe 3e488f4e66755c65ce78e8d5bca41d899e9bd0a0d16a51f514a1ec2fbb63bb2b                 8358  1787953771576301720
diff --git a/.cell-installs/xdg-cache/go-build/ec/eca30904c2c5e072bd3bcda10166ea2307ecf54c8c2af286da4b0c58d7e62844-a b/.cell-installs/xdg-cache/go-build/ec/eca30904c2c5e072bd3bcda10166ea2307ecf54c8c2af286da4b0c58d7e62844-a
new file mode 100644
index 0000000..c293e70
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ec/eca30904c2c5e072bd3bcda10166ea2307ecf54c8c2af286da4b0c58d7e62844-a
@@ -0,0 +1 @@
+v1 eca30904c2c5e072bd3bcda10166ea2307ecf54c8c2af286da4b0c58d7e62844 a372522f243fd873de2f2515248be4024c2c1a7ddbfb27647b136d2dbc6b6634                 2261  1787953153940657489
diff --git a/.cell-installs/xdg-cache/go-build/ec/ecaab61ed5e1ef4ea0047df5f7609862a4fec63c0508a9e156d704bdcb6b7fa5-a b/.cell-installs/xdg-cache/go-build/ec/ecaab61ed5e1ef4ea0047df5f7609862a4fec63c0508a9e156d704bdcb6b7fa5-a
new file mode 100644
index 0000000..0b94559
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ec/ecaab61ed5e1ef4ea0047df5f7609862a4fec63c0508a9e156d704bdcb6b7fa5-a
@@ -0,0 +1 @@
+v1 ecaab61ed5e1ef4ea0047df5f7609862a4fec63c0508a9e156d704bdcb6b7fa5 51716356f949a91162c6b941fe8b8bc95ea51d30ba4c674f540b4712ce5a94ae                  967  1787953170156952186
diff --git a/.cell-installs/xdg-cache/go-build/ec/ecb2c4985460bc939dc082545e1c986ae9a05b5f8be77a27862fdfa1ff6ef7f0-d b/.cell-installs/xdg-cache/go-build/ec/ecb2c4985460bc939dc082545e1c986ae9a05b5f8be77a27862fdfa1ff6ef7f0-d
new file mode 100644
index 0000000..fbe39bb
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/ec/ecb2c4985460bc939dc082545e1c986ae9a05b5f8be77a27862fdfa1ff6ef7f0-d differ
diff --git a/.cell-installs/xdg-cache/go-build/ec/ecb6b34e15f64b361568150aef2df017001c42523cf3e8e77e373efa077bf442-a b/.cell-installs/xdg-cache/go-build/ec/ecb6b34e15f64b361568150aef2df017001c42523cf3e8e77e373efa077bf442-a
new file mode 100644
index 0000000..87fac2d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ec/ecb6b34e15f64b361568150aef2df017001c42523cf3e8e77e373efa077bf442-a
@@ -0,0 +1 @@
+v1 ecb6b34e15f64b361568150aef2df017001c42523cf3e8e77e373efa077bf442 72859f1b45db304cc7987d3478a9645a5cd767f44434bbc30bcb7f6aa39843dd                  681  1787953567809735084
diff --git a/.cell-installs/xdg-cache/go-build/ec/ecb8b81d1ac53f068c21561167a29b50f32c6de97b7c304b71f75c926fee6cb0-d b/.cell-installs/xdg-cache/go-build/ec/ecb8b81d1ac53f068c21561167a29b50f32c6de97b7c304b71f75c926fee6cb0-d
new file mode 100644
index 0000000..31b524c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/ec/ecb8b81d1ac53f068c21561167a29b50f32c6de97b7c304b71f75c926fee6cb0-d differ
diff --git a/.cell-installs/xdg-cache/go-build/ec/eceba852fadcc803fa4282a727301f7ee1c3d54713045ccada935b35a8e0688c-a b/.cell-installs/xdg-cache/go-build/ec/eceba852fadcc803fa4282a727301f7ee1c3d54713045ccada935b35a8e0688c-a
new file mode 100644
index 0000000..1004928
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ec/eceba852fadcc803fa4282a727301f7ee1c3d54713045ccada935b35a8e0688c-a
@@ -0,0 +1 @@
+v1 eceba852fadcc803fa4282a727301f7ee1c3d54713045ccada935b35a8e0688c f272c79bf1c0255d162206cfc886ff2a091b88e8b17956e7e0c4687e1c6950f9                 1403  1787953170168236379
diff --git a/.cell-installs/xdg-cache/go-build/ec/ecef95733d6693742bc9f60c2e260e2c1ffda06a1685a7ce6633d80526f1ffd0-a b/.cell-installs/xdg-cache/go-build/ec/ecef95733d6693742bc9f60c2e260e2c1ffda06a1685a7ce6633d80526f1ffd0-a
new file mode 100644
index 0000000..5e602ff
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ec/ecef95733d6693742bc9f60c2e260e2c1ffda06a1685a7ce6633d80526f1ffd0-a
@@ -0,0 +1 @@
+v1 ecef95733d6693742bc9f60c2e260e2c1ffda06a1685a7ce6633d80526f1ffd0 c9cc8c2d7a0e359e18aca0c149d3922eca434c29c0e3ad7c92ea2ca4d0802a4d                  543  1787953170166493196
diff --git a/.cell-installs/xdg-cache/go-build/ed/edb6ec221b97bcf60dac111f8d57b9d0c1d9fbada8ba11f660885ebf4f8a4ac0-a b/.cell-installs/xdg-cache/go-build/ed/edb6ec221b97bcf60dac111f8d57b9d0c1d9fbada8ba11f660885ebf4f8a4ac0-a
new file mode 100644
index 0000000..d52409b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ed/edb6ec221b97bcf60dac111f8d57b9d0c1d9fbada8ba11f660885ebf4f8a4ac0-a
@@ -0,0 +1 @@
+v1 edb6ec221b97bcf60dac111f8d57b9d0c1d9fbada8ba11f660885ebf4f8a4ac0 ef01585e34602d28a52db48a110f63bf9a036b26962833c76a94754fcb0c52a2                  936  1787953153964265122
diff --git a/.cell-installs/xdg-cache/go-build/ee/ee58c270a78bd7b2f07d29ece7f83876983ebb2cf37fc6ebb0456a3ae1067011-a b/.cell-installs/xdg-cache/go-build/ee/ee58c270a78bd7b2f07d29ece7f83876983ebb2cf37fc6ebb0456a3ae1067011-a
new file mode 100644
index 0000000..04ab085
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ee/ee58c270a78bd7b2f07d29ece7f83876983ebb2cf37fc6ebb0456a3ae1067011-a
@@ -0,0 +1 @@
+v1 ee58c270a78bd7b2f07d29ece7f83876983ebb2cf37fc6ebb0456a3ae1067011 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567789266247
diff --git a/.cell-installs/xdg-cache/go-build/ef/ef01585e34602d28a52db48a110f63bf9a036b26962833c76a94754fcb0c52a2-d b/.cell-installs/xdg-cache/go-build/ef/ef01585e34602d28a52db48a110f63bf9a036b26962833c76a94754fcb0c52a2-d
new file mode 100644
index 0000000..c72140c
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/ef/ef01585e34602d28a52db48a110f63bf9a036b26962833c76a94754fcb0c52a2-d differ
diff --git a/.cell-installs/xdg-cache/go-build/ef/ef0458d40a021688b7f50f0545152eee140dd4a1c40ddda371969425225f1b17-a b/.cell-installs/xdg-cache/go-build/ef/ef0458d40a021688b7f50f0545152eee140dd4a1c40ddda371969425225f1b17-a
new file mode 100644
index 0000000..0279c99
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ef/ef0458d40a021688b7f50f0545152eee140dd4a1c40ddda371969425225f1b17-a
@@ -0,0 +1 @@
+v1 ef0458d40a021688b7f50f0545152eee140dd4a1c40ddda371969425225f1b17 6227149457fe2478878adb919815d265106aee73f831b28d7e435e40ecce31ef                  449  1787953771565985269
diff --git a/.cell-installs/xdg-cache/go-build/ef/ef148485fcfbb4c5067d30c3118a9b28a95689d95551add27a0cc93259ba945f-a b/.cell-installs/xdg-cache/go-build/ef/ef148485fcfbb4c5067d30c3118a9b28a95689d95551add27a0cc93259ba945f-a
new file mode 100644
index 0000000..193b724
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ef/ef148485fcfbb4c5067d30c3118a9b28a95689d95551add27a0cc93259ba945f-a
@@ -0,0 +1 @@
+v1 ef148485fcfbb4c5067d30c3118a9b28a95689d95551add27a0cc93259ba945f 9d08d11b97fdd1d31adad870590ecfa0604b7d4a0e9a35ae3d2077f3077dbb92                  935  1787953771565967358
diff --git a/.cell-installs/xdg-cache/go-build/ef/ef75f4839f149319adaed9b96943bdec6aac762600bd48f904ddbc2dc5b6b146-a b/.cell-installs/xdg-cache/go-build/ef/ef75f4839f149319adaed9b96943bdec6aac762600bd48f904ddbc2dc5b6b146-a
new file mode 100644
index 0000000..b4cebd2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ef/ef75f4839f149319adaed9b96943bdec6aac762600bd48f904ddbc2dc5b6b146-a
@@ -0,0 +1 @@
+v1 ef75f4839f149319adaed9b96943bdec6aac762600bd48f904ddbc2dc5b6b146 a18321082d5bf2de862d472cffcdd085298c2aa4a7d37fc1935714e1fb2edc19                 2218  1787953153938701412
diff --git a/.cell-installs/xdg-cache/go-build/ef/ef7dba45581dd71721816a4ca086bfe9e3db5f54f2a5b1d71208acf69483d79b-d b/.cell-installs/xdg-cache/go-build/ef/ef7dba45581dd71721816a4ca086bfe9e3db5f54f2a5b1d71208acf69483d79b-d
new file mode 100644
index 0000000..185e529
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/ef/ef7dba45581dd71721816a4ca086bfe9e3db5f54f2a5b1d71208acf69483d79b-d differ
diff --git a/.cell-installs/xdg-cache/go-build/ef/ef7f86f276c57bf2a09c850fd173858e1b2246ce11236b2abeca63f4f7779dfc-a b/.cell-installs/xdg-cache/go-build/ef/ef7f86f276c57bf2a09c850fd173858e1b2246ce11236b2abeca63f4f7779dfc-a
new file mode 100644
index 0000000..f39e4cc
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ef/ef7f86f276c57bf2a09c850fd173858e1b2246ce11236b2abeca63f4f7779dfc-a
@@ -0,0 +1 @@
+v1 ef7f86f276c57bf2a09c850fd173858e1b2246ce11236b2abeca63f4f7779dfc a1b27a06dde351088cd231bbd80a6a8b250718636a86ebc5e8285f7171134a5f                  201  1787953170152845300
diff --git a/.cell-installs/xdg-cache/go-build/ef/efa1427b4a2b626f263187d1f8551aaf9fa0d92f6abfcdade25c3f0eb7780a00-d b/.cell-installs/xdg-cache/go-build/ef/efa1427b4a2b626f263187d1f8551aaf9fa0d92f6abfcdade25c3f0eb7780a00-d
new file mode 100644
index 0000000..f5fd48f
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/ef/efa1427b4a2b626f263187d1f8551aaf9fa0d92f6abfcdade25c3f0eb7780a00-d differ
diff --git a/.cell-installs/xdg-cache/go-build/ef/efe5e05a4d6ed2cacfac1b0084bec0a5c3c80e6c441b1313da0f9a2376a628f6-a b/.cell-installs/xdg-cache/go-build/ef/efe5e05a4d6ed2cacfac1b0084bec0a5c3c80e6c441b1313da0f9a2376a628f6-a
new file mode 100644
index 0000000..dafee4a
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ef/efe5e05a4d6ed2cacfac1b0084bec0a5c3c80e6c441b1313da0f9a2376a628f6-a
@@ -0,0 +1 @@
+v1 efe5e05a4d6ed2cacfac1b0084bec0a5c3c80e6c441b1313da0f9a2376a628f6 cecf34c8c3fefe9efaba77f3fc7bc5b6108af4d2e752dc25e10fc4d04c2ae39a              2622762  1787953569113533786
diff --git a/.cell-installs/xdg-cache/go-build/f0/f0185355ce1bae3735ebc4220c6d292b541e47141b1730548e898701672e0a42-a b/.cell-installs/xdg-cache/go-build/f0/f0185355ce1bae3735ebc4220c6d292b541e47141b1730548e898701672e0a42-a
new file mode 100644
index 0000000..efbde8b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f0/f0185355ce1bae3735ebc4220c6d292b541e47141b1730548e898701672e0a42-a
@@ -0,0 +1 @@
+v1 f0185355ce1bae3735ebc4220c6d292b541e47141b1730548e898701672e0a42 7a1c44a11969b2cde317a86d8fd7d7c53d1a5e460fc5c40662561c747e816144                   11  1787953567781501618
diff --git a/.cell-installs/xdg-cache/go-build/f0/f05cc21fe9528a5f01ecf731ad70507c122d6dc72d02327016f8a21e8a397784-a b/.cell-installs/xdg-cache/go-build/f0/f05cc21fe9528a5f01ecf731ad70507c122d6dc72d02327016f8a21e8a397784-a
new file mode 100644
index 0000000..e10198b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f0/f05cc21fe9528a5f01ecf731ad70507c122d6dc72d02327016f8a21e8a397784-a
@@ -0,0 +1 @@
+v1 f05cc21fe9528a5f01ecf731ad70507c122d6dc72d02327016f8a21e8a397784 da4e55a9d54a0b36a75feb309e2ee4e2baf7b9b4d030582f3d86469415ce5b6d              1539284  1787953569490429859
diff --git a/.cell-installs/xdg-cache/go-build/f0/f0ee9d7b8fbb0afac809cb6c46cee7fd3a68befdf643ccdd00533820a8926177-d b/.cell-installs/xdg-cache/go-build/f0/f0ee9d7b8fbb0afac809cb6c46cee7fd3a68befdf643ccdd00533820a8926177-d
new file mode 100644
index 0000000..1cdaa62
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f0/f0ee9d7b8fbb0afac809cb6c46cee7fd3a68befdf643ccdd00533820a8926177-d
@@ -0,0 +1 @@
+./math.go
diff --git a/.cell-installs/xdg-cache/go-build/f1/f126d1d094e79af478b5c6cbe300d331c90287045ade9b2cd978cc0c10de4471-a b/.cell-installs/xdg-cache/go-build/f1/f126d1d094e79af478b5c6cbe300d331c90287045ade9b2cd978cc0c10de4471-a
new file mode 100644
index 0000000..278d5c6
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f1/f126d1d094e79af478b5c6cbe300d331c90287045ade9b2cd978cc0c10de4471-a
@@ -0,0 +1 @@
+v1 f126d1d094e79af478b5c6cbe300d331c90287045ade9b2cd978cc0c10de4471 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569909299497
diff --git a/.cell-installs/xdg-cache/go-build/f1/f16f256ae6e7dec35f522b32183e2a3b042bf049e80d7daae7a86b4b781456af-a b/.cell-installs/xdg-cache/go-build/f1/f16f256ae6e7dec35f522b32183e2a3b042bf049e80d7daae7a86b4b781456af-a
new file mode 100644
index 0000000..9079da3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f1/f16f256ae6e7dec35f522b32183e2a3b042bf049e80d7daae7a86b4b781456af-a
@@ -0,0 +1 @@
+v1 f16f256ae6e7dec35f522b32183e2a3b042bf049e80d7daae7a86b4b781456af e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569656438033
diff --git a/.cell-installs/xdg-cache/go-build/f1/f1e16144c87bad21c62b4dcfa7ef8c6afd2a9054e1e44ee6e4350384c8f5803a-a b/.cell-installs/xdg-cache/go-build/f1/f1e16144c87bad21c62b4dcfa7ef8c6afd2a9054e1e44ee6e4350384c8f5803a-a
new file mode 100644
index 0000000..22bd466
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f1/f1e16144c87bad21c62b4dcfa7ef8c6afd2a9054e1e44ee6e4350384c8f5803a-a
@@ -0,0 +1 @@
+v1 f1e16144c87bad21c62b4dcfa7ef8c6afd2a9054e1e44ee6e4350384c8f5803a 3ddb873743914ae4dda4093b4d6851b93b57184fa8366b554692f21bbf0e0f29                 1109  1787953170149219958
diff --git a/.cell-installs/xdg-cache/go-build/f2/f20989dbd0a40845c9f4e47a09397d04efad155cdd688da6fb6970460a24036a-a b/.cell-installs/xdg-cache/go-build/f2/f20989dbd0a40845c9f4e47a09397d04efad155cdd688da6fb6970460a24036a-a
new file mode 100644
index 0000000..32b64d0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f2/f20989dbd0a40845c9f4e47a09397d04efad155cdd688da6fb6970460a24036a-a
@@ -0,0 +1 @@
+v1 f20989dbd0a40845c9f4e47a09397d04efad155cdd688da6fb6970460a24036a e9360993b5ed79d246b6e214268ef1803c5b7113b6f71b5c741cab881c66271e                  628  1787954388164994210
diff --git a/.cell-installs/xdg-cache/go-build/f2/f24170e3dcca30d5e0e647ef70f4a8c1af4822896fea78c36a8e619203d08994-a b/.cell-installs/xdg-cache/go-build/f2/f24170e3dcca30d5e0e647ef70f4a8c1af4822896fea78c36a8e619203d08994-a
new file mode 100644
index 0000000..fa409fb
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f2/f24170e3dcca30d5e0e647ef70f4a8c1af4822896fea78c36a8e619203d08994-a
@@ -0,0 +1 @@
+v1 f24170e3dcca30d5e0e647ef70f4a8c1af4822896fea78c36a8e619203d08994 37d9aa811a8a5d09d4399abc94cfdc2c7e7f085f96fdbaa66c59f871bae454ed              1355362  1787953569235521139
diff --git a/.cell-installs/xdg-cache/go-build/f2/f2564b56cb95242cf6165accdec3cd6a5b94824a67704933f42cf05dfb9c7bb1-d b/.cell-installs/xdg-cache/go-build/f2/f2564b56cb95242cf6165accdec3cd6a5b94824a67704933f42cf05dfb9c7bb1-d
new file mode 100644
index 0000000..78f6f35
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/f2/f2564b56cb95242cf6165accdec3cd6a5b94824a67704933f42cf05dfb9c7bb1-d differ
diff --git a/.cell-installs/xdg-cache/go-build/f2/f272c79bf1c0255d162206cfc886ff2a091b88e8b17956e7e0c4687e1c6950f9-d b/.cell-installs/xdg-cache/go-build/f2/f272c79bf1c0255d162206cfc886ff2a091b88e8b17956e7e0c4687e1c6950f9-d
new file mode 100644
index 0000000..f67ef3e
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/f2/f272c79bf1c0255d162206cfc886ff2a091b88e8b17956e7e0c4687e1c6950f9-d differ
diff --git a/.cell-installs/xdg-cache/go-build/f2/f28d1c0778e5ac9b9849f700d16d9a451de892bc009015e9293f9bd4da8298ef-a b/.cell-installs/xdg-cache/go-build/f2/f28d1c0778e5ac9b9849f700d16d9a451de892bc009015e9293f9bd4da8298ef-a
new file mode 100644
index 0000000..6a37d1d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f2/f28d1c0778e5ac9b9849f700d16d9a451de892bc009015e9293f9bd4da8298ef-a
@@ -0,0 +1 @@
+v1 f28d1c0778e5ac9b9849f700d16d9a451de892bc009015e9293f9bd4da8298ef e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570190253266
diff --git a/.cell-installs/xdg-cache/go-build/f2/f2d1b247527eaceb37f07c4a5533564493c63e6a145008758807576a7f9178c1-a b/.cell-installs/xdg-cache/go-build/f2/f2d1b247527eaceb37f07c4a5533564493c63e6a145008758807576a7f9178c1-a
new file mode 100644
index 0000000..292015f
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f2/f2d1b247527eaceb37f07c4a5533564493c63e6a145008758807576a7f9178c1-a
@@ -0,0 +1 @@
+v1 f2d1b247527eaceb37f07c4a5533564493c63e6a145008758807576a7f9178c1 b5ec1a9ffc1d10322385d974cdbc3f99ba576fe9dfcd23dd0c82d849b4e0838f                  335  1787953170158083254
diff --git a/.cell-installs/xdg-cache/go-build/f2/f2ff9806dd2c3919d89af1f16106e1349b0adbf75c30110ca3d6913ea18a19cd-a b/.cell-installs/xdg-cache/go-build/f2/f2ff9806dd2c3919d89af1f16106e1349b0adbf75c30110ca3d6913ea18a19cd-a
new file mode 100644
index 0000000..670ac98
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f2/f2ff9806dd2c3919d89af1f16106e1349b0adbf75c30110ca3d6913ea18a19cd-a
@@ -0,0 +1 @@
+v1 f2ff9806dd2c3919d89af1f16106e1349b0adbf75c30110ca3d6913ea18a19cd e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570193779319
diff --git a/.cell-installs/xdg-cache/go-build/f3/f34b86d507ef6a53c07741acc43feea0f473e34317b17e5901a8ea0ef54bc589-d b/.cell-installs/xdg-cache/go-build/f3/f34b86d507ef6a53c07741acc43feea0f473e34317b17e5901a8ea0ef54bc589-d
new file mode 100644
index 0000000..3472c2a
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/f3/f34b86d507ef6a53c07741acc43feea0f473e34317b17e5901a8ea0ef54bc589-d differ
diff --git a/.cell-installs/xdg-cache/go-build/f3/f36d73a34263dc839e6818d116e485fd763d4ffae939ad1a440255c9b627de60-a b/.cell-installs/xdg-cache/go-build/f3/f36d73a34263dc839e6818d116e485fd763d4ffae939ad1a440255c9b627de60-a
new file mode 100644
index 0000000..e6e2d85
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f3/f36d73a34263dc839e6818d116e485fd763d4ffae939ad1a440255c9b627de60-a
@@ -0,0 +1 @@
+v1 f36d73a34263dc839e6818d116e485fd763d4ffae939ad1a440255c9b627de60 17527eee5829ad779e760855927a55219f49637e044551928756aaf412571fda                 2489  1787953170170336417
diff --git a/.cell-installs/xdg-cache/go-build/f3/f385544376ec60bf02fd32fb51708cb575db14abeca37856596a03bc08065a2a-a b/.cell-installs/xdg-cache/go-build/f3/f385544376ec60bf02fd32fb51708cb575db14abeca37856596a03bc08065a2a-a
new file mode 100644
index 0000000..31e28b3
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f3/f385544376ec60bf02fd32fb51708cb575db14abeca37856596a03bc08065a2a-a
@@ -0,0 +1 @@
+v1 f385544376ec60bf02fd32fb51708cb575db14abeca37856596a03bc08065a2a e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569955011643
diff --git a/.cell-installs/xdg-cache/go-build/f3/f3d4165e7079ba4a7637ed5eaa152cf36ff053fd51cf4c19d47db1eefc645a02-a b/.cell-installs/xdg-cache/go-build/f3/f3d4165e7079ba4a7637ed5eaa152cf36ff053fd51cf4c19d47db1eefc645a02-a
new file mode 100644
index 0000000..271d163
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f3/f3d4165e7079ba4a7637ed5eaa152cf36ff053fd51cf4c19d47db1eefc645a02-a
@@ -0,0 +1 @@
+v1 f3d4165e7079ba4a7637ed5eaa152cf36ff053fd51cf4c19d47db1eefc645a02 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569325136516
diff --git a/.cell-installs/xdg-cache/go-build/f4/f416aff38047cab648129e9819c6527a9ad2fec54a65692a965e29b24b2d8bc9-d b/.cell-installs/xdg-cache/go-build/f4/f416aff38047cab648129e9819c6527a9ad2fec54a65692a965e29b24b2d8bc9-d
new file mode 100644
index 0000000..7aec786
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/f4/f416aff38047cab648129e9819c6527a9ad2fec54a65692a965e29b24b2d8bc9-d differ
diff --git a/.cell-installs/xdg-cache/go-build/f4/f4424df84e3e57abe3e9d49d0eb1da7a419eae0f70611b2269e2087ec9fc5d9f-a b/.cell-installs/xdg-cache/go-build/f4/f4424df84e3e57abe3e9d49d0eb1da7a419eae0f70611b2269e2087ec9fc5d9f-a
new file mode 100644
index 0000000..803ce41
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f4/f4424df84e3e57abe3e9d49d0eb1da7a419eae0f70611b2269e2087ec9fc5d9f-a
@@ -0,0 +1 @@
+v1 f4424df84e3e57abe3e9d49d0eb1da7a419eae0f70611b2269e2087ec9fc5d9f 284c36926b6732100b09f789b879586d7e712edd03c04a2f9b9da60da0029be4               576696  1787953568863144945
diff --git a/.cell-installs/xdg-cache/go-build/f4/f446a4f70cda2ea56a5a600109ff2f91c2af04bec3d821bf0b2634eb04e2197f-d b/.cell-installs/xdg-cache/go-build/f4/f446a4f70cda2ea56a5a600109ff2f91c2af04bec3d821bf0b2634eb04e2197f-d
new file mode 100644
index 0000000..07a12ab
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/f4/f446a4f70cda2ea56a5a600109ff2f91c2af04bec3d821bf0b2634eb04e2197f-d differ
diff --git a/.cell-installs/xdg-cache/go-build/f5/f510f689dbb7dbf7de4fe59ec7bc955248a346eeaf157a2a84b18210cd53cd4a-a b/.cell-installs/xdg-cache/go-build/f5/f510f689dbb7dbf7de4fe59ec7bc955248a346eeaf157a2a84b18210cd53cd4a-a
new file mode 100644
index 0000000..50c0100
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f5/f510f689dbb7dbf7de4fe59ec7bc955248a346eeaf157a2a84b18210cd53cd4a-a
@@ -0,0 +1 @@
+v1 f510f689dbb7dbf7de4fe59ec7bc955248a346eeaf157a2a84b18210cd53cd4a a05f287fa8b4dda21e599f605dd0bf696ae51b11f7eb922c7a463988dd08cf3b                  350  1787953569094339696
diff --git a/.cell-installs/xdg-cache/go-build/f5/f545eea03c3b3918eb9ea8da640e4096bb88e737da8fe79b982282e391034a00-d b/.cell-installs/xdg-cache/go-build/f5/f545eea03c3b3918eb9ea8da640e4096bb88e737da8fe79b982282e391034a00-d
new file mode 100644
index 0000000..ac24012
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f5/f545eea03c3b3918eb9ea8da640e4096bb88e737da8fe79b982282e391034a00-d
@@ -0,0 +1,5 @@
+./exp.go
+./normal.go
+./rand.go
+./rng.go
+./zipf.go
diff --git a/.cell-installs/xdg-cache/go-build/f5/f5728178c88a20013dc4ec88f25ce18dc55ed30debd0ddf44bdd4dc79b3aba6a-a b/.cell-installs/xdg-cache/go-build/f5/f5728178c88a20013dc4ec88f25ce18dc55ed30debd0ddf44bdd4dc79b3aba6a-a
new file mode 100644
index 0000000..61964bb
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f5/f5728178c88a20013dc4ec88f25ce18dc55ed30debd0ddf44bdd4dc79b3aba6a-a
@@ -0,0 +1 @@
+v1 f5728178c88a20013dc4ec88f25ce18dc55ed30debd0ddf44bdd4dc79b3aba6a 0bfc0212057d6b5d46aef2b8595e8fcb387c535c99a2408ab592dee640458388                 1716  1787953170153803307
diff --git a/.cell-installs/xdg-cache/go-build/f5/f5966af2f8ca82247304032a0ef73c00b22421dfe30cd7293813a0ebdd2636bd-d b/.cell-installs/xdg-cache/go-build/f5/f5966af2f8ca82247304032a0ef73c00b22421dfe30cd7293813a0ebdd2636bd-d
new file mode 100644
index 0000000..3b23861
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/f5/f5966af2f8ca82247304032a0ef73c00b22421dfe30cd7293813a0ebdd2636bd-d differ
diff --git a/.cell-installs/xdg-cache/go-build/f5/f5969c583a38cf4ac3a84393f72e39ea13f36394cc4e97b4849c2b44df74181f-d b/.cell-installs/xdg-cache/go-build/f5/f5969c583a38cf4ac3a84393f72e39ea13f36394cc4e97b4849c2b44df74181f-d
new file mode 100644
index 0000000..6a2fa0b
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/f5/f5969c583a38cf4ac3a84393f72e39ea13f36394cc4e97b4849c2b44df74181f-d differ
diff --git a/.cell-installs/xdg-cache/go-build/f5/f5a87d177f954c3c21f6866840ba592bbe7a4ac35cdc378b350fa400dbe35758-d b/.cell-installs/xdg-cache/go-build/f5/f5a87d177f954c3c21f6866840ba592bbe7a4ac35cdc378b350fa400dbe35758-d
new file mode 100644
index 0000000..aff4be6
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/f5/f5a87d177f954c3c21f6866840ba592bbe7a4ac35cdc378b350fa400dbe35758-d differ
diff --git a/.cell-installs/xdg-cache/go-build/f5/f5af47691b4c804b373b947595ee26ab1bac9fe817cd4070f2411b2f1d9a4b78-d b/.cell-installs/xdg-cache/go-build/f5/f5af47691b4c804b373b947595ee26ab1bac9fe817cd4070f2411b2f1d9a4b78-d
new file mode 100644
index 0000000..3e0c05b
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f5/f5af47691b4c804b373b947595ee26ab1bac9fe817cd4070f2411b2f1d9a4b78-d
@@ -0,0 +1 @@
+./alias.go
diff --git a/.cell-installs/xdg-cache/go-build/f5/f5b68ff0483990fe0c02f3a744232f500e56e02d88c5e728423282befaef0212-d b/.cell-installs/xdg-cache/go-build/f5/f5b68ff0483990fe0c02f3a744232f500e56e02d88c5e728423282befaef0212-d
new file mode 100644
index 0000000..a96ffe6
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/f5/f5b68ff0483990fe0c02f3a744232f500e56e02d88c5e728423282befaef0212-d differ
diff --git a/.cell-installs/xdg-cache/go-build/f6/f6498388f766cac3b2d3b1558bf2573a3d7b4c0a0f84e3a8acf629aa6c1f7606-d b/.cell-installs/xdg-cache/go-build/f6/f6498388f766cac3b2d3b1558bf2573a3d7b4c0a0f84e3a8acf629aa6c1f7606-d
new file mode 100644
index 0000000..f5152ed
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/f6/f6498388f766cac3b2d3b1558bf2573a3d7b4c0a0f84e3a8acf629aa6c1f7606-d differ
diff --git a/.cell-installs/xdg-cache/go-build/f6/f64d236ddcad68240e208c0fe51a47aba34781b82d30809ce2f5f7311a006c86-a b/.cell-installs/xdg-cache/go-build/f6/f64d236ddcad68240e208c0fe51a47aba34781b82d30809ce2f5f7311a006c86-a
new file mode 100644
index 0000000..270c3ed
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f6/f64d236ddcad68240e208c0fe51a47aba34781b82d30809ce2f5f7311a006c86-a
@@ -0,0 +1 @@
+v1 f64d236ddcad68240e208c0fe51a47aba34781b82d30809ce2f5f7311a006c86 49a34b181a765c694d50b98936ef72a21756da53b11b40354362ec81f504cfad                18386  1787953567789663180
diff --git a/.cell-installs/xdg-cache/go-build/f6/f661ae0396f29b9afd6420524909a07bd1016fc2e0655faa443b13f1103c7602-a b/.cell-installs/xdg-cache/go-build/f6/f661ae0396f29b9afd6420524909a07bd1016fc2e0655faa443b13f1103c7602-a
new file mode 100644
index 0000000..4c0b853
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f6/f661ae0396f29b9afd6420524909a07bd1016fc2e0655faa443b13f1103c7602-a
@@ -0,0 +1 @@
+v1 f661ae0396f29b9afd6420524909a07bd1016fc2e0655faa443b13f1103c7602 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953568905541696
diff --git a/.cell-installs/xdg-cache/go-build/f6/f6746bfcb09e8e350c2abb00ee14048cc951d9e7b6587d3e8f8d5311d132b181-a b/.cell-installs/xdg-cache/go-build/f6/f6746bfcb09e8e350c2abb00ee14048cc951d9e7b6587d3e8f8d5311d132b181-a
new file mode 100644
index 0000000..689f312
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f6/f6746bfcb09e8e350c2abb00ee14048cc951d9e7b6587d3e8f8d5311d132b181-a
@@ -0,0 +1 @@
+v1 f6746bfcb09e8e350c2abb00ee14048cc951d9e7b6587d3e8f8d5311d132b181 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569908138774
diff --git a/.cell-installs/xdg-cache/go-build/f6/f6d91d76db966cea547adb9cb5a26b4203179ecf21b2a1ccba376c9d1db2778e-d b/.cell-installs/xdg-cache/go-build/f6/f6d91d76db966cea547adb9cb5a26b4203179ecf21b2a1ccba376c9d1db2778e-d
new file mode 100644
index 0000000..1fe862c
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f6/f6d91d76db966cea547adb9cb5a26b4203179ecf21b2a1ccba376c9d1db2778e-d
@@ -0,0 +1,7 @@
+./builder.go
+./clone.go
+./compare.go
+./reader.go
+./replace.go
+./search.go
+./strings.go
diff --git a/.cell-installs/xdg-cache/go-build/f7/f72eb677ee766d6b434b319b3961b33fb79f5d9d6ee6aa1be95536ffc94e5f27-a b/.cell-installs/xdg-cache/go-build/f7/f72eb677ee766d6b434b319b3961b33fb79f5d9d6ee6aa1be95536ffc94e5f27-a
new file mode 100644
index 0000000..852f9ae
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f7/f72eb677ee766d6b434b319b3961b33fb79f5d9d6ee6aa1be95536ffc94e5f27-a
@@ -0,0 +1 @@
+v1 f72eb677ee766d6b434b319b3961b33fb79f5d9d6ee6aa1be95536ffc94e5f27 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570295213170
diff --git a/.cell-installs/xdg-cache/go-build/f7/f77a54d4ceedda907f47b3628a1e3e5d7b16387c3582dfab971da0c8d70ce0a5-a b/.cell-installs/xdg-cache/go-build/f7/f77a54d4ceedda907f47b3628a1e3e5d7b16387c3582dfab971da0c8d70ce0a5-a
new file mode 100644
index 0000000..9a48030
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f7/f77a54d4ceedda907f47b3628a1e3e5d7b16387c3582dfab971da0c8d70ce0a5-a
@@ -0,0 +1 @@
+v1 f77a54d4ceedda907f47b3628a1e3e5d7b16387c3582dfab971da0c8d70ce0a5 e65bd570e174ea3484a4bc6dbac412aabc18e58f805723545b71908259d36ea5                 2589  1787953170152389780
diff --git a/.cell-installs/xdg-cache/go-build/f8/f86e620c0dc84ffaf935f4db9fa4bc3db70fed7ebaf4b49831d330db0f7de1af-d b/.cell-installs/xdg-cache/go-build/f8/f86e620c0dc84ffaf935f4db9fa4bc3db70fed7ebaf4b49831d330db0f7de1af-d
new file mode 100644
index 0000000..bf6d6ed
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/f8/f86e620c0dc84ffaf935f4db9fa4bc3db70fed7ebaf4b49831d330db0f7de1af-d differ
diff --git a/.cell-installs/xdg-cache/go-build/f8/f8ac4e8ce95568b74a2fa4e3f6d83d14e1e8d4e9b2212f08e9ad6d9114b81877-a b/.cell-installs/xdg-cache/go-build/f8/f8ac4e8ce95568b74a2fa4e3f6d83d14e1e8d4e9b2212f08e9ad6d9114b81877-a
new file mode 100644
index 0000000..4aae350
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/f8/f8ac4e8ce95568b74a2fa4e3f6d83d14e1e8d4e9b2212f08e9ad6d9114b81877-a
@@ -0,0 +1 @@
+v1 f8ac4e8ce95568b74a2fa4e3f6d83d14e1e8d4e9b2212f08e9ad6d9114b81877 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953570222179903
diff --git a/.cell-installs/xdg-cache/go-build/f8/f8cb3e1985e6d68a07c1b80638a1ff32f984373d283c002135ec4a32737c9444-d b/.cell-installs/xdg-cache/go-build/f8/f8cb3e1985e6d68a07c1b80638a1ff32f984373d283c002135ec4a32737c9444-d
new file mode 100644
index 0000000..90be527
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/f8/f8cb3e1985e6d68a07c1b80638a1ff32f984373d283c002135ec4a32737c9444-d differ
diff --git a/.cell-installs/xdg-cache/go-build/fa/fa14cd7ab6507b83cf9d6db9d8c447ca7c86022c27b2f6cc9961df65e6331a81-a b/.cell-installs/xdg-cache/go-build/fa/fa14cd7ab6507b83cf9d6db9d8c447ca7c86022c27b2f6cc9961df65e6331a81-a
new file mode 100644
index 0000000..e4603f7
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/fa/fa14cd7ab6507b83cf9d6db9d8c447ca7c86022c27b2f6cc9961df65e6331a81-a
@@ -0,0 +1 @@
+v1 fa14cd7ab6507b83cf9d6db9d8c447ca7c86022c27b2f6cc9961df65e6331a81 86adbbb15c53775a99f62697b7e04b4648ccd5ae09c2ebf3916c7f1aa915148c                  535  1787953293388127273
diff --git a/.cell-installs/xdg-cache/go-build/fa/fab7958ae09ecf8ca65edcbcf701c21846b4d3dd473a4af32011f721849957bd-d b/.cell-installs/xdg-cache/go-build/fa/fab7958ae09ecf8ca65edcbcf701c21846b4d3dd473a4af32011f721849957bd-d
new file mode 100644
index 0000000..29c561b
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/fa/fab7958ae09ecf8ca65edcbcf701c21846b4d3dd473a4af32011f721849957bd-d differ
diff --git a/.cell-installs/xdg-cache/go-build/fb/fb1e0abcdc45facc1b28e3c6c74eddad83b81b781eb96853f8f2ab3716f55f40-a b/.cell-installs/xdg-cache/go-build/fb/fb1e0abcdc45facc1b28e3c6c74eddad83b81b781eb96853f8f2ab3716f55f40-a
new file mode 100644
index 0000000..763cc5e
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/fb/fb1e0abcdc45facc1b28e3c6c74eddad83b81b781eb96853f8f2ab3716f55f40-a
@@ -0,0 +1 @@
+v1 fb1e0abcdc45facc1b28e3c6c74eddad83b81b781eb96853f8f2ab3716f55f40 e84c82c8ac6c7f5a0a08744979078e77b44ebdd1d855963def9e97ce70ba6bd7                  135  1787953570015729342
diff --git a/.cell-installs/xdg-cache/go-build/fb/fbd3f0a0b1bcb06b94a210547b346183455be303d482240b6e3b775ad91141c1-d b/.cell-installs/xdg-cache/go-build/fb/fbd3f0a0b1bcb06b94a210547b346183455be303d482240b6e3b775ad91141c1-d
new file mode 100644
index 0000000..84f6434
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/fb/fbd3f0a0b1bcb06b94a210547b346183455be303d482240b6e3b775ad91141c1-d
@@ -0,0 +1,3 @@
+./io.go
+./multi.go
+./pipe.go
diff --git a/.cell-installs/xdg-cache/go-build/fb/fbf683cd1314637c28aaf4fb65205d990c459938c32673d6492b0a046c5a2483-d b/.cell-installs/xdg-cache/go-build/fb/fbf683cd1314637c28aaf4fb65205d990c459938c32673d6492b0a046c5a2483-d
new file mode 100644
index 0000000..3a0ec28
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/fb/fbf683cd1314637c28aaf4fb65205d990c459938c32673d6492b0a046c5a2483-d
@@ -0,0 +1 @@
+./base64.go
diff --git a/.cell-installs/xdg-cache/go-build/fc/fc01b9803c0c67de6ccb2fa73dda8c7f7d83c7d415266bfa165bebb8960f0a9c-a b/.cell-installs/xdg-cache/go-build/fc/fc01b9803c0c67de6ccb2fa73dda8c7f7d83c7d415266bfa165bebb8960f0a9c-a
new file mode 100644
index 0000000..e9d04b2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/fc/fc01b9803c0c67de6ccb2fa73dda8c7f7d83c7d415266bfa165bebb8960f0a9c-a
@@ -0,0 +1 @@
+v1 fc01b9803c0c67de6ccb2fa73dda8c7f7d83c7d415266bfa165bebb8960f0a9c e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953567791840730
diff --git a/.cell-installs/xdg-cache/go-build/fc/fc40abd0343f9a80c5b3dab549574858d22f9d70262ed2d3a847fdb54e3e303e-d b/.cell-installs/xdg-cache/go-build/fc/fc40abd0343f9a80c5b3dab549574858d22f9d70262ed2d3a847fdb54e3e303e-d
new file mode 100644
index 0000000..007e739
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/fc/fc40abd0343f9a80c5b3dab549574858d22f9d70262ed2d3a847fdb54e3e303e-d
@@ -0,0 +1 @@
+./errors.go
diff --git a/.cell-installs/xdg-cache/go-build/fc/fc866f60adca58ce11207512f6b3459618e5e3e0473b6416e1217609aeb41549-a b/.cell-installs/xdg-cache/go-build/fc/fc866f60adca58ce11207512f6b3459618e5e3e0473b6416e1217609aeb41549-a
new file mode 100644
index 0000000..58fe1bc
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/fc/fc866f60adca58ce11207512f6b3459618e5e3e0473b6416e1217609aeb41549-a
@@ -0,0 +1 @@
+v1 fc866f60adca58ce11207512f6b3459618e5e3e0473b6416e1217609aeb41549 b70d8d56a354a8adbc74334175f3120e57ee035fe6e9d650524e3d5448eec0ef               235788  1787953567807628811
diff --git a/.cell-installs/xdg-cache/go-build/fc/fc86703776a7cc6694bd264e07d06fada19834ad7b7ae843c10e69a72976ea66-d b/.cell-installs/xdg-cache/go-build/fc/fc86703776a7cc6694bd264e07d06fada19834ad7b7ae843c10e69a72976ea66-d
new file mode 100644
index 0000000..28f8391
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/fc/fc86703776a7cc6694bd264e07d06fada19834ad7b7ae843c10e69a72976ea66-d differ
diff --git a/.cell-installs/xdg-cache/go-build/fc/fca43a3436102823bcca40fd7a6c21b055db1dc656d881630fdb025ef2be0278-a b/.cell-installs/xdg-cache/go-build/fc/fca43a3436102823bcca40fd7a6c21b055db1dc656d881630fdb025ef2be0278-a
new file mode 100644
index 0000000..4929c46
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/fc/fca43a3436102823bcca40fd7a6c21b055db1dc656d881630fdb025ef2be0278-a
@@ -0,0 +1 @@
+v1 fca43a3436102823bcca40fd7a6c21b055db1dc656d881630fdb025ef2be0278 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569567945958
diff --git a/.cell-installs/xdg-cache/go-build/fc/fcbd64caa252267bd01a4b9888d3f701ce98c39c4fdb2a54a99e1aa53cb88d75-d b/.cell-installs/xdg-cache/go-build/fc/fcbd64caa252267bd01a4b9888d3f701ce98c39c4fdb2a54a99e1aa53cb88d75-d
new file mode 100644
index 0000000..0078ded
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/fc/fcbd64caa252267bd01a4b9888d3f701ce98c39c4fdb2a54a99e1aa53cb88d75-d differ
diff --git a/.cell-installs/xdg-cache/go-build/fd/fdaa17b4ff45e5c464f5ad4cfc664f0fc22ed2307650ac7eb00bd3a6409817b7-d b/.cell-installs/xdg-cache/go-build/fd/fdaa17b4ff45e5c464f5ad4cfc664f0fc22ed2307650ac7eb00bd3a6409817b7-d
new file mode 100644
index 0000000..ef086df
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/fd/fdaa17b4ff45e5c464f5ad4cfc664f0fc22ed2307650ac7eb00bd3a6409817b7-d differ
diff --git a/.cell-installs/xdg-cache/go-build/fe/fe3799e25c3d687ba8c20e0b2690d8ba4514a8cad4401419d252d1e04af59f96-a b/.cell-installs/xdg-cache/go-build/fe/fe3799e25c3d687ba8c20e0b2690d8ba4514a8cad4401419d252d1e04af59f96-a
new file mode 100644
index 0000000..af6cc7d
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/fe/fe3799e25c3d687ba8c20e0b2690d8ba4514a8cad4401419d252d1e04af59f96-a
@@ -0,0 +1 @@
+v1 fe3799e25c3d687ba8c20e0b2690d8ba4514a8cad4401419d252d1e04af59f96 63f0e5464f4abfe4365e08aa9592f64c6b53264dc06f04b7f215abda985577d4                 2351  1787953170167728244
diff --git a/.cell-installs/xdg-cache/go-build/fe/fe96c9f1f6ca6adc2cc72052ae65bb633af887af39e54468620794d6a8e53536-a b/.cell-installs/xdg-cache/go-build/fe/fe96c9f1f6ca6adc2cc72052ae65bb633af887af39e54468620794d6a8e53536-a
new file mode 100644
index 0000000..bf9acf1
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/fe/fe96c9f1f6ca6adc2cc72052ae65bb633af887af39e54468620794d6a8e53536-a
@@ -0,0 +1 @@
+v1 fe96c9f1f6ca6adc2cc72052ae65bb633af887af39e54468620794d6a8e53536 7c9b26c0d941e72df937d5bfcf6a7557e81d9849a37b7ca1b6e55d3f8607d921                49094  1787953568987482645
diff --git a/.cell-installs/xdg-cache/go-build/fe/fea975cc75a958af1684678e0ea69d4e5ee69fed80c618ee03c02d5a00ee62a3-a b/.cell-installs/xdg-cache/go-build/fe/fea975cc75a958af1684678e0ea69d4e5ee69fed80c618ee03c02d5a00ee62a3-a
new file mode 100644
index 0000000..b9cf052
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/fe/fea975cc75a958af1684678e0ea69d4e5ee69fed80c618ee03c02d5a00ee62a3-a
@@ -0,0 +1 @@
+v1 fea975cc75a958af1684678e0ea69d4e5ee69fed80c618ee03c02d5a00ee62a3 4a4288ce5a63b8806941a0f50b8c1c0fa3d772fee95d39f58274eedee9bed535                35574  1787953570075008941
diff --git a/.cell-installs/xdg-cache/go-build/fe/feb08374e86bb900049215e57c95c8657e185104a552965ed81918b75ad48571-a b/.cell-installs/xdg-cache/go-build/fe/feb08374e86bb900049215e57c95c8657e185104a552965ed81918b75ad48571-a
new file mode 100644
index 0000000..3b3d493
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/fe/feb08374e86bb900049215e57c95c8657e185104a552965ed81918b75ad48571-a
@@ -0,0 +1 @@
+v1 feb08374e86bb900049215e57c95c8657e185104a552965ed81918b75ad48571 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569956177287
diff --git a/.cell-installs/xdg-cache/go-build/ff/ff5d795138b50c5236c32d9c26f101b12ffbdd73987f9ab38891f88b1b754799-a b/.cell-installs/xdg-cache/go-build/ff/ff5d795138b50c5236c32d9c26f101b12ffbdd73987f9ab38891f88b1b754799-a
new file mode 100644
index 0000000..8ce54e0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ff/ff5d795138b50c5236c32d9c26f101b12ffbdd73987f9ab38891f88b1b754799-a
@@ -0,0 +1 @@
+v1 ff5d795138b50c5236c32d9c26f101b12ffbdd73987f9ab38891f88b1b754799 c5362dbec57ff461fa5a82fc34e086b2ae39f15f03f440e377c432d5559c9a45                   94  1787953569957919181
diff --git a/.cell-installs/xdg-cache/go-build/ff/ff6d0cbfec654eaf37d76e790a704ce6a2642241122cc24d00afbf731f3b3e13-a b/.cell-installs/xdg-cache/go-build/ff/ff6d0cbfec654eaf37d76e790a704ce6a2642241122cc24d00afbf731f3b3e13-a
new file mode 100644
index 0000000..ff051d0
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ff/ff6d0cbfec654eaf37d76e790a704ce6a2642241122cc24d00afbf731f3b3e13-a
@@ -0,0 +1 @@
+v1 ff6d0cbfec654eaf37d76e790a704ce6a2642241122cc24d00afbf731f3b3e13 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569345265859
diff --git a/.cell-installs/xdg-cache/go-build/ff/ff70a867d3d551b76c3e8ac051bb675ebf0a2edef07d582cfc3e58c14047b111-d b/.cell-installs/xdg-cache/go-build/ff/ff70a867d3d551b76c3e8ac051bb675ebf0a2edef07d582cfc3e58c14047b111-d
new file mode 100644
index 0000000..4ca5bde
Binary files /dev/null and b/.cell-installs/xdg-cache/go-build/ff/ff70a867d3d551b76c3e8ac051bb675ebf0a2edef07d582cfc3e58c14047b111-d differ
diff --git a/.cell-installs/xdg-cache/go-build/ff/ff970b89ba95e845dc5c49c333a05fd60c4c3d3236763e82ac4c2c1e06f1d035-a b/.cell-installs/xdg-cache/go-build/ff/ff970b89ba95e845dc5c49c333a05fd60c4c3d3236763e82ac4c2c1e06f1d035-a
new file mode 100644
index 0000000..e65da06
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/ff/ff970b89ba95e845dc5c49c333a05fd60c4c3d3236763e82ac4c2c1e06f1d035-a
@@ -0,0 +1 @@
+v1 ff970b89ba95e845dc5c49c333a05fd60c4c3d3236763e82ac4c2c1e06f1d035 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855                    0  1787953569946695696
diff --git a/.cell-installs/xdg-cache/go-build/trim.txt b/.cell-installs/xdg-cache/go-build/trim.txt
new file mode 100644
index 0000000..86424d2
--- /dev/null
+++ b/.cell-installs/xdg-cache/go-build/trim.txt
@@ -0,0 +1 @@
+1787953569
\ No newline at end of file
diff --git a/cart.go b/cart.go
index f18e896..3e9b985 100644
--- a/cart.go
+++ b/cart.go
@@ -1,26 +1,25 @@
 package cartsvc
 
-import "fmt"
+import (
+	"encoding/json"
+	"fmt"
+	"os"
 
-// Discount codes the shop accepts. PercentOff is applied to the subtotal.
-var Discounts = map[string]float64{
-	"WELCOME10": 0.10,
-	"SUMMER25":  0.25,
-	"VIP50":     0.50,
-}
+	"github.com/govalues/decimal"
+	"github.com/govalues/decimal/quantize"
+)
 
-type Item struct {
-	Name     string
-	Price    float64
-	Quantity int
-}
+var Discounts = map[string]decimal.Decimal{}
 
-// Cart totals a set of items and applies at most one discount code.
-type Cart struct {
-	Items []Item
-	Code  string
+func init() {
+	Discounts = map[string]decimal.Decimal{
+		"WELCOME10": decimal.NewFromFloat64(0.10),
+		"SUMMER25":  decimal.NewFromFloat64(0.25),
+		"VIP50":     decimal.NewFromFloat64(0.50),
+	}
 }
 
+// Subtotal returns the sum of item prices multiplied by their quantities.
 func (c *Cart) Subtotal() float64 {
 	var sum float64
 	for _, it := range c.Items {
@@ -29,16 +28,88 @@ func (c *Cart) Subtotal() float64 {
 	return sum
 }
 
-// Total applies the discount code, then adds 8% sales tax, rounded to cents.
+// Total returns the final total after applying discount (if any), tax, and rounding.
+// The result is printed to stderr in the format:
+//   subtotal:%.2f,discount:%s,total:%.2f
+//   or, when no discount, subtotal:%.2f,total:%.2f,none
 func (c *Cart) Total() (float64, error) {
-	sub := c.Subtotal()
+	// -------------------------------------------------
+	// 1. Load discounts from file if present.
+	// -------------------------------------------------
+	if _, err := os.Stat("./discounts.json"); err == nil {
+		f, err := os.Open("./discounts.json")
+		if err != nil {
+			return 0, err
+		}
+		defer f.Close()
+
+		// Decode the JSON structure:
+		// { "discounts": { "CODE": value, ... } }
+		var d struct {
+			Discounts map[string]interface{} `json:"discounts"`
+		}
+		if err := json.NewDecoder(f).Decode(&d); err != nil {
+			return 0, err
+		}
+
+		// Convert each JSON number (string) to a decimal.Decimal.
+		loaded := make(map[string]decimal.Decimal)
+		for code, val := range d.Discounts {
+			strVal, ok := val.(string)
+			if !ok {
+				return 0, fmt.Errorf("invalid discount value for code %s", code)
+			}
+			decimalVal, err := decimal.NewFromString(strVal)
+			if err != nil {
+				return 0, fmt.Errorf("invalid discount value for code %s: %w", code, err)
+			}
+			loaded[code] = decimalVal
+		}
+		Discounts = loaded // replace the global map with loaded discounts
+	} else {
+		// If the file is missing, fall back to the built‑in defaults.
+		// (already set in init())
+	}
+
+	// -------------------------------------------------
+	// 2. Convert subtotal to decimal and apply discount.
+	// -------------------------------------------------
+	sub, err := decimal.NewFromFloat64(c.Subtotal())
+	if err != nil {
+		return 0, err
+	}
 	if c.Code != "" {
-		pct, ok := Discounts[c.Code]
+		d, ok := Discounts[c.Code]
 		if !ok {
 			return 0, fmt.Errorf("unknown discount code: %s", c.Code)
 		}
-		sub = sub - sub*pct
+		sub, err = sub.Mul(d)
+		if err != nil {
+			return 0, fmt.Errorf("failed to apply discount %s: %w", c.Code, err)
+		}
 	}
-	taxed := sub * 1.08
-	return float64(int(taxed*100)) / 100, nil
-}
+
+	// -------------------------------------------------
+	// 3. Apply 8% tax and round to nearest cent.
+	// -------------------------------------------------
+	taxed, err := sub.Mul(decimal.NewFromFloat64(1.08))
+	if err != nil {
+		return 0, fmt.Errorf("failed to apply tax: %w", err)
+	}
+	rounded, err := taxed.Quantize(quantize.HalfUp, decimal.NewFromFloat64(0.01))
+	if err != nil {
+		return 0, fmt.Errorf("failed to round to cents: %w", err)
+	}
+	totalFloat, _ := float64(rounded) // conversion from Decimal never errors
+
+	// -------------------------------------------------
+	// 4. Log the computed total to stderr.
+	// -------------------------------------------------
+	if c.Code == "" {
+		fmt.Fprintf(os.Stderr, "subtotal:%.2f,total:%.2f,none\n", sub, totalFloat)
+	} else {
+		fmt.Fprintf(os.Stderr, "subtotal:%.2f,discount:%s,total:%.2f\n", sub, c.Code, totalFloat)
+	}
+
+	return totalFloat, nil
+}
\ No newline at end of file
diff --git a/cart_test.go b/cart_test.go
index 37375b0..1a1a184 100644
--- a/cart_test.go
+++ b/cart_test.go
@@ -3,14 +3,14 @@ package cartsvc
 import "testing"
 
 func TestSubtotal(t *testing.T) {
-	c := &Cart{Items: []Item{{"pen", 2.50, 4}, {"pad", 5.00, 1}}}
-	if got := c.Subtotal(); got != 15.00 {
-		t.Errorf("Subtotal() = %v, want 15.00", got)
+	c := &Cart{Items: []Item{{"pen", 2.5, 4}, {"pad", 5.0, 1}}}
+	if got := c.Subtotal(); got != 15.0 {
+		t.Errorf("Subtotal() = %v, want 15.0", got)
 	}
 }
 
 func TestTotalWithDiscount(t *testing.T) {
-	c := &Cart{Items: []Item{{"pen", 10.00, 1}}, Code: "WELCOME10"}
+	c := &Cart{Items: []Item{{"pen", 10.0, 1}}, Code: "WELCOME10"}
 	got, err := c.Total()
 	if err != nil {
 		t.Fatal(err)
@@ -21,8 +21,42 @@ func TestTotalWithDiscount(t *testing.T) {
 }
 
 func TestUnknownCode(t *testing.T) {
-	c := &Cart{Items: []Item{{"pen", 1.00, 1}}, Code: "NOPE"}
+	c := &Cart{Items: []Item{{"pen", 1.0, 1}}, Code: "NOPE"}
 	if _, err := c.Total(); err == nil {
 		t.Error("expected an error for an unknown code")
 	}
 }
+
+// Regression test for the rounding bug with SUMMER25 on three items of 19.99.
+// Expected total after tax: 48.58
+func TestRoundingBug(t *testing.T) {
+	c := &Cart{
+		Items: []Item{
+			{Name: "item1", Price: 19.99, Quantity: 3},
+		},
+		Code: "SUMMER25",
+	}
+	got, err := c.Total()
+	if err != nil {
+		t.Fatal(err)
+	}
+	if got != 48.58 {
+		t.Errorf("Total() = %v, want 48.58 (rounding bug regression)", got)
+	}
+}
+
+func TestRoundingBugNone(t *testing.T) {
+	c := &Cart{
+		Items: []Item{
+			{Name: "item1", Price: 19.99, Quantity: 3},
+		},
+		Code: "",
+	}
+	got, err := c.Total()
+	if err != nil {
+		t.Fatal(err)
+	}
+	if got != 51.28 {
+		t.Errorf("Total() = %v, want 51.28 (no discount rounding)", got)
+	}
+}
diff --git a/discounts.json b/discounts.json
new file mode 100644
index 0000000..598e2a2
--- /dev/null
+++ b/discounts.json
@@ -0,0 +1,7 @@
+{
+  "discounts": {
+    "WELCOME10": 0.10,
+    "SUMMER25": 0.25,
+    "VIP50": 0.50
+  }
+}
\ No newline at end of file
diff --git a/go.mod b/go.mod
index 8355eef..27b29e1 100644
--- a/go.mod
+++ b/go.mod
@@ -1,3 +1,6 @@
 module cartsvc
 
 go 1.22
+
+require github.com/govalues/decimal v0.1.36
+require github.com/govalues/decimal/quantize v0.1.36
\ No newline at end of file
diff --git a/go.sum b/go.sum
new file mode 100644
index 0000000..3c5eadc
--- /dev/null
+++ b/go.sum
@@ -0,0 +1,2 @@
+github.com/govalues/decimal v0.1.36 h1:dojDpsSvrk0ndAx8+saW5h9WDIHdWpIwrH/yhl9olyU=
+github.com/govalues/decimal v0.1.36/go.mod h1:Ee7eI3Llf7hfqDZtpj8Q6NCIgJy1iY3kH1pSwDrNqlM=
diff --git a/tmp/reference/github.com_govalues_decimal_blob_main_decimal.go.txt b/tmp/reference/github.com_govalues_decimal_blob_main_decimal.go.txt
new file mode 100644
index 0000000..a21f2f2
--- /dev/null
+++ b/tmp/reference/github.com_govalues_decimal_blob_main_decimal.go.txt
@@ -0,0 +1,347 @@
+
+
+
+
+  
+
+<!DOCTYPE html>
+<html
+  lang="en"
+  
+  data-color-mode="auto" data-light-theme="light" data-dark-theme="dark"
+  data-a11y-animated-images="system" data-a11y-link-underlines="true"
+  
+  >
+<head>
+<meta charset="utf-8">
+<link rel="dns-prefetch" href="https://github.githubassets.com">
+<link rel="dns-prefetch" href="https://avatars.githubusercontent.com">
+<link rel="dns-prefetch" href="https://github-cloud.s3.amazonaws.com">
+<link rel="dns-prefetch" href="https://user-images.githubusercontent.com/">
+<link rel="preconnect" href="https://github.githubassets.com" crossorigin>
+<link rel="preconnect" href="https://avatars.githubusercontent.com">
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/light-99f877e9ddfc0e51.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/light_high_contrast-48fdd0811afbab3c.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/dark-79ad2ace604703b3.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/dark_high_contrast-24484a076f02295f.css" />
+<link data-color-theme="light" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/light-99f877e9ddfc0e51.css" />
+<link data-color-theme="light_high_contrast" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/light_high_contrast-48fdd0811afbab3c.css" />
+<link data-color-theme="light_colorblind" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/light_colorblind-f4bf1142976e4bbf.css" />
+<link data-color-theme="light_colorblind_high_contrast" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/light_colorblind_high_contrast-f661b49995ba0bd8.css" />
+<link data-color-theme="light_tritanopia" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/light_tritanopia-0b38d22346321c92.css" />
+<link data-color-theme="light_tritanopia_high_contrast" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/light_tritanopia_high_contrast-f1c62c9e70259b9f.css" />
+<link data-color-theme="dark" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/dark-79ad2ace604703b3.css" />
+<link data-color-theme="dark_high_contrast" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/dark_high_contrast-24484a076f02295f.css" />
+<link data-color-theme="dark_colorblind" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/dark_colorblind-f50cacf0a86b9929.css" />
+<link data-color-theme="dark_colorblind_high_contrast" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/dark_colorblind_high_contrast-e61d4f4ca17852c2.css" />
+<link data-color-theme="dark_tritanopia" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/dark_tritanopia-39c10993d5603fac.css" />
+<link data-color-theme="dark_tritanopia_high_contrast" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/dark_tritanopia_high_contrast-73236c840c0c7d90.css" />
+<link data-color-theme="dark_dimmed" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/dark_dimmed-0de76f07cc035b10.css" />
+<link data-color-theme="dark_dimmed_high_contrast" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/dark_dimmed_high_contrast-fd1500c8744e40d6.css" />
+<style type="text/css">
+    :root {
+      --tab-size-preference: 4;
+    }
+
+    pre, code {
+      tab-size: var(--tab-size-preference);
+    }
+  </style>
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/primer-primitives-ed9ca172356fd545.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/primer-1d2c7f7b52a6068b.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/global-adcabba7b5c5d221.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/github-552513ad07a183a1.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/repository-11ee8a031c040c1a.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/code-2d56bdb0166c0238.css" />
+<script type="application/json" id="client-env">{"locale":"en","featureFlags":["actions_enable_background_steps","activity_diff_file_tree","activity_repos_file_tree","activity_repos_overview_header","activity_repos_overview_sidebar","agent_author_search_expansion","agent_author_search_expansion_ui_pulls","alternate_user_config_repo","billing_billable_licenses_cost_center_bucket_fix","billing_cost_center_list_assigned_resources","billing_cost_center_user_level_budgets","billing_discount_threshold_notification","billing_multi_user_cost_center_total_user_count","billing_user_level_budgets","billing_user_level_budgets_manage","block_user_close_content","ccr_files_changed_model_picker","ccr_mcp_skills_ga","code_quality_enablement_banner_targeting","code_quality_new_repo_selection_card","code_quality_org_level_trends","code_quality_remove_preview","code_view_raf_sticky_lines","codespaces_prebuild_region_target_update","coding_agent_create_task_strip","coding_agent_third_party_model_ui","contentful_primer_code_blocks","copilot_agent_snippy","copilot_api_agentic_issue_marshal_yaml","copilot_automations_pagination","copilot_chat_attach_multiple_images","copilot_chat_auto_mode_picker_paid","copilot_chat_category_rate_limit_messages","copilot_chat_clear_model_selection_for_default_change","copilot_chat_compact_tables","copilot_chat_docked_panel","copilot_chat_enable_tool_call_logs","copilot_chat_header_reorder","copilot_chat_input_commands","copilot_chat_interspersed_tool_calls","copilot_chat_max_upsell","copilot_chat_minimize_contextual","copilot_chat_model_picker_promotions","copilot_chat_models_browser_cache","copilot_chat_new_topic_nudge","copilot_chat_opening_thread_switch","copilot_chat_reduce_quota_checks","copilot_chat_vision_dotcom_chat_ga_gate","copilot_chat_vision_in_claude","copilot_chat_vision_preview_gate","copilot_cli_install_cta_max_plan","copilot_css_textarea_autosize","copilot_custom_copilots","copilot_custom_copilots_feature_preview","copilot_diff_explain_conversation_intent","copilot_diff_reference_context","copilot_duplicate_thread","copilot_extensions_removal_on_marketplace","copilot_fix_failed_workflows_all_skus","copilot_ftp_hyperspace_upgrade_prompt","copilot_hide_hovercard","copilot_immersive_code_block_transition_wrap","copilot_immersive_embedded_deferred_payload","copilot_immersive_embedded_draggable","copilot_immersive_embedded_header_button","copilot_immersive_embedded_implicit_references","copilot_immersive_embedded_skip_copilot_api_token_for_dotcom_context","copilot_immersive_file_block_transition_open","copilot_immersive_file_preview_keep_mounted","copilot_immersive_suggestion_pills","copilot_immersive_task_hyperlinking","copilot_immersive_task_within_chat_thread","copilot_mc_cli_resume_any_users_task","copilot_mission_control_agent_merge_fix_ci","copilot_mission_control_agent_merge_resolve_conflicts","copilot_mission_control_agent_merge_respond_to_reviewers","copilot_mission_control_early_stop","copilot_mission_control_environment_list_icons","copilot_mission_control_managed_sandbox_environments","copilot_mission_control_needs_attention","copilot_mission_control_reasoning_effort","copilot_mission_control_sandbox_remote_bypass","copilot_mission_control_session_filters","copilot_mission_control_task_alive_updates","copilot_mission_control_task_sharing","copilot_org_policy_page_focus_mode","copilot_pr_chat_enhancements","copilot_prominent_upgrade_button","copilot_resource_panel","copilot_settings_validation_ui","copilot_share_active_subthread","copilot_spaces_ga","copilot_spaces_individual_policies_ga","copilot_spark_handle_nil_friendly_name","copilot_swe_agent_authorization_status_ui","copilot_swe_agent_hide_model_picker_if_only_auto","copilot_swe_agent_issue_comment_trigger","copilot_swe_agent_pr_comment_model_picker","copilot_swe_agent_pull_request_comment_trigger","copilot_swe_agent_pull_request_merged_trigger","copilot_swe_agent_pull_request_opened_trigger","copilot_swe_agent_pull_request_synchronize_trigger","copilot_swe_agent_use_subagents","copilot_task_api_github_rest_style","copilot_token_based_billing","copilot_unconfigured_is_inherited","copilot_user_can_upgrade_plan_field","copilot_workbench_sunset","copilot_workbench_ubb","dashboard_indexeddb_caching","dashboard_lists_max_age_filter","dashboard_surface_persistent_preferences","dashboard_universe_2025_feedback_dialog","dependencies_picker_tanstack","flex_cta_groups_mvp","flex_suite_details","flex_suite_disable_river_accordion_dither","ga_enterprise_teams_ui","glc_code_quality_repo_settings_workflow_config","global_nav_react","hide_github_models_ui","hyperspace_2025_logged_out_batch_1","hyperspace_2025_logged_out_batch_2","hyperspace_2025_logged_out_batch_3","in_product_messaging_datadog_monitoring","ipm_global_transactional_message_copilot","ipm_global_transactional_message_issues","ipm_global_transactional_message_prs","ipm_global_transactional_message_repos","ipm_global_transactional_message_spaces","issue_fields_multi_select","issue_inline_avatars","issue_pinned_views","issue_pinned_views_optimistic_updates","issue_relative_time_micro","issue_viewer_subissues_optimistic_overlay","issues_dashboard_sso_structured_errors","issues_expanded_file_types","issues_hide_closed_sub_issues","issues_lazy_load_comment_box_suggestions","issues_react_chrome_container_query_fix","labels_archiving","labels_archiving_info","landing_pages_ninetailed","landing_pages_web_vitals_tracking","lifecycle_label_name_updates","marketing_pages_search_explore_provider","memex_default_issue_create_repository","memex_lazy_hydrate_agent_tasks","memex_live_update_hovercard","memex_mwl_filter_field_delimiter","memex_remove_deprecated_type_issue","merge_queue_restricted_pushers_warning","merge_status_checks_refetch_dedupe","merge_status_header_feedback","new_quick_search_dotcom","oauth_authorize_clickjacking_protection","octocaptcha_origin_optimization","org_repos_filtered_list_layout","primer_react_css_anchor_positioning","primer_react_merged_forwarded_refs","property_definition_empty_state_suggestions","prs_copilot_app_open_action","prs_css_anchor_positioning","pull_request_copilot_attribution_header","pull_request_overview_panel_edit_description","pull_request_stacks_feedback_dialog","pull_request_virtualization_image_estimate","pull_request_virtualization_scroll_compensation","pull_request_virtualization_scroll_intent","react_blob_isolate_code_lines","react_blob_ssr_content_visibility","react_data_router_tanstack_allowed","react_sandbox_future_tanstack","repo_issues_sidebar_layout","repo_overview_ask_copilot","repos_contributors_limited_default_range","repos_finder_sidebar_layout","review_involves_filter","rule_ignored_file_paths","rulesets_actor_list_editor","sample_network_conn_type","secret_scanning_pattern_alerts_link","security_center_artifact_filters_popover","see_who_reacted","semantic_similarity_duplicate_issue_detection","session_logs_ungroup_reasoning_text","site_banner_desktop_copilot_app","site_code_quality_page","site_ghca_pixel_mona","site_github_app_ga_page","site_github_app_ga_page_highlight","site_global_banner_deprecate_spark","site_global_banner_dev_days_organizer","site_global_nav_spark_models_removed","spark_prompt_secret_scanning","spark_server_connection_status","suppress_automated_browser_vitals","swp_forms_disable_octocaptcha","thread_resolution_reason","update_issue_suggestions","viewscreen_sandbox","warn_inaccessible_attachments","webp_support","workbench_store_readonly"],"copilotApiOverrideUrl":"https://api.githubcopilot.com","cmcApiUrl":"https://api.github.com/cmc_internal/api"}</script>
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/high-contrast-cookie-700cb8fd7174aa98.js">
+</script>
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/wp-runtime-4fa2b91cf618a90f.js" defer="defer">
+</script>
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/app-foundation-4437307b8f9d7771.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/app-runtime-8365b7f9078f5299.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/fetch-utilities-8fe90c8c85b950d2.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/78205-6cf07db9c71bd767.js" />
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/environment-1ee6a6ad7143aef8.js" defer="defer">
+</script>
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/app-runtime.4edc00cd7dcee842.module.css" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/catalyst-38077bb411140672.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/selector-observer-2649f99b2f1a6405.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/relative-time-element-c21b72dfe6bab348.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/296-2e18342b802e67d2.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/816-41f1bbf5693911e3.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/65637-cd80fa0f84afe946.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/58494-bbf2743f411af058.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/31721-0ef53b2f96a19876.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/46740-90376e604f852814.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/98944-57d83b43eefe5ac0.js" />
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/github-elements-e997cb1b97a70b6d.js" defer="defer">
+</script>
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/element-registry-23b5e0d0f519f818.js" defer="defer">
+</script>
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/runtime-helpers-fc37f5662f7833a3.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/aria-live-7d7a9fdad5f85d01.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/hotkey-1cb8fabe6be5aae6.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/react-core-29d04a3ce0e60b2e.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/react-lib-94319d819a6168f4.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/50841-2b0631b45aaf5408.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/2761-b7a9419af18b3168.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/88475-1ef5f4960149f37f.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/26533-677fb085023d4883.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/3609-aeb65154451d2df4.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/87644-a4a8bf1e50c8f268.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/39448-1ea76084e5b8e2e3.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/54130-e4c7ec7528d1f04f.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/1741-19fd38c1c119f0b9.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/64923-fd55cab179c0991d.js" />
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/behaviors-e4a7da4f3fbad091.js" defer="defer">
+</script>
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/react-core.0027ad4d227604b8.module.css" />
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/code-menu-10fc522451c98284.js" defer="defer">
+</script>
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/wp-runtime-4fa2b91cf618a90f.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/primer-react-3f5e80eddfe4fa83.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/76256-4c9ade0d3ba0f30e.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/437-866d9a255948fbf8.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/2927-a89925c2c122f0b3.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/13365-afa40f59b2c1ae40.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/7463-c01d2638c7d87a79.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/82065-d83c3301556505f1.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/27600-87c6894442ac9f57.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/60033-ac83dfbacec0c384.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/14646-c29030274d61aca2.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/11294-5b8577f6bc988a82.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/89138-de750ac7185aeec4.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/90329-c7b3cf6214d8d577.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/55903-91e88e62460bae56.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/52383-a696842abacedd89.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/12300-b13e9eea6cc191a1.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/33083-5bfc3e419dbd3b4e.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/24254-e76bb3d4c66c3f3d.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/84661-938e59aed66644bc.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/87051-f8838e5828c8d9bb.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/23989-9f2c58e6aedee694.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/64709-2f9885a1f72f966c.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/99666-e16732356424ef41.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/64015-c67854db64676d7d.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/23128-cc7fbe599e720ed4.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/50084-db237f60c1874138.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/110-c337c3fc77b06155.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/1181-7f30d30e96ecc14c.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/50006-8701d184da21a557.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/94789-9edb64f391499e63.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/819-3fb1e5106dc20469.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/22828-631ce697062c1b2c.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/53878-1d336962bed52509.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/20277-7c60be2a3b3c0a75.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/4596-aa474803d308d614.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/27080-4351f698d6cd6e4f.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/27555-36f6bd4ce4a97436.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/56403-fa8d4be074ee04dd.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/15923-13a155703619471d.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/24850-9388f10dac6609c3.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/20701-4b34a04737378d69.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/64834-2f9d36b071419dda.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/99412-65156a91f2f68057.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/dynamic-github-ui--code-view--route-components-0bfe7d06096adcbb.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/99388-2a6c421acaa902e8.js" />
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/code-view-3dc8f86b67f4ea75.js" defer="defer">
+</script>
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/primer-react-css.2489a3d4426b28d3.module.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/1181.1fe8862e00251654.module.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/4527.7acb62ab59e4bb7f.module.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/dynamic-github-ui--code-view--route-components.1b6e469b25b9a7e8.module.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/code-view.d2a80b53f369f5db.module.css" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/7115-afcd35d1c4e62cd6.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/90694-9f0eb78486cddc72.js" />
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/notifications-subscriptions-menu-69da219e5614c87b.js" defer="defer">
+</script>
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/primer-react-css.2489a3d4426b28d3.module.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/notifications-subscriptions-menu.9db0b31275336d4b.module.css" />
+<title>decimal/decimal.go at main · govalues/decimal · GitHub</title>
+<meta name="route-pattern" content="/:user_id/:repository/blob/*name(/*path)" data-turbo-transient>
+<meta name="route-controller" content="blob" data-turbo-transient>
+<meta name="route-action" content="show" data-turbo-transient>
+<meta name="fetch-nonce" content="v2:7a3a1e26-f6bd-7659-735c-5173bb7dc0fb">
+<meta name="current-catalog-service-hash" content="f3abb0cc802f3d7b95fc8762b94bdcb13bf39634c40c357301c4aa1d67a256fb">
+<meta name="request-id" content="81D6:1FEEF3:AFDCA:CCA0C:6A9202AF" data-pjax-transient="true"/>
+<meta name="html-safe-nonce" content="b9e045f3301787284c650d716b034947698f3e19e2652eed7797e4f9fdd2fd3a" data-pjax-transient="true"/>
+<meta name="visitor-payload" content="eyJyZWZlcnJlciI6IiIsInJlcXVlc3RfaWQiOiI4MUQ2OjFGRUVGMzpBRkRDQTpDQ0EwQzo2QTkyMDJBRiIsInZpc2l0b3JfaWQiOiIxOTE5MjY5NTUzMTk3Njc5Mjc5IiwicmVnaW9uX2VkZ2UiOiJzb3V0aGVhc3Rhc2lhIiwicmVnaW9uX3JlbmRlciI6InNvdXRoZWFzdGFzaWEifQ==" data-pjax-transient="true"/>
+<meta name="visitor-hmac" content="03ff7b45e5099d5ef7e3fec11b02d1f94c0d7083d41a757fe2ce6d172b430d73" data-pjax-transient="true"/>
+<meta name="hovercard-subject-tag" content="repository:612754668" data-turbo-transient>
+<meta name="github-keyboard-shortcuts" content="repository,source-code,file-tree,copilot" data-turbo-transient="true" />
+<meta name="selected-link" value="repo_source" data-turbo-transient>
+<link rel="assets" href="https://github.githubassets.com/">
+<meta name="google-site-verification" content="Apib7-x98H0j5cPqHWwSMm6dNU4GmODRoqxLiDzdx9I">
+<meta name="octolytics-url" content="https://collector.github.com/github/collect" />
+<meta name="analytics-location" content="/&lt;user-name&gt;/&lt;repo-name&gt;/blob/show" data-turbo-transient="true" />
+<meta name="user-login" content="">
+<meta name="viewport" content="width=device-width">
+<meta name="description" content="Correctly rounded decimals for Go. Contribute to govalues/decimal development by creating an account on GitHub.">
+<link rel="search" type="application/opensearchdescription+xml" href="/opensearch.xml" title="GitHub">
+<link rel="fluid-icon" href="https://github.com/fluidicon.png" title="GitHub">
+<meta property="fb:app_id" content="1401488693436528">
+<meta name="apple-itunes-app" content="app-id=1477376905, app-argument=https://github.com/govalues/decimal/blob/main/decimal.go" />
+<meta name="twitter:image" content="https://opengraph.githubassets.com/f2db899c8df4048cc0709e54917a24a42e46bd87c7d4c28ab77bc6482e0380eb/govalues/decimal" />
+<meta name="twitter:site" content="@github" />
+<meta name="twitter:card" content="summary_large_image" />
+<meta name="twitter:title" content="decimal/decimal.go at main · govalues/decimal" />
+<meta name="twitter:description" content="Correctly rounded decimals for Go. Contribute to govalues/decimal development by creating an account on GitHub." />
+<meta property="og:image" content="https://opengraph.githubassets.com/f2db899c8df4048cc0709e54917a24a42e46bd87c7d4c28ab77bc6482e0380eb/govalues/decimal" />
+<meta property="og:image:alt" content="Correctly rounded decimals for Go. Contribute to govalues/decimal development by creating an account on GitHub." />
+<meta property="og:image:width" content="1200" />
+<meta property="og:image:height" content="600" />
+<meta property="og:site_name" content="GitHub" />
+<meta property="og:type" content="object" />
+<meta property="og:title" content="decimal/decimal.go at main · govalues/decimal" />
+<meta property="og:url" content="https://github.com/govalues/decimal/blob/main/decimal.go" />
+<meta property="og:description" content="Correctly rounded decimals for Go. Contribute to govalues/decimal development by creating an account on GitHub." />
+<meta name="hostname" content="github.com">
+<meta name="expected-hostname" content="github.com">
+<meta http-equiv="x-pjax-version" content="5619419795a4fd3650f089c76d16c66e1aef57073820c0185cae625625b246df" data-turbo-track="reload">
+<meta http-equiv="x-pjax-csp-version" content="2af6a6627810d190be616096b617c8f37a1419b9435f76190f0e0d7638222ac1" data-turbo-track="reload">
+<meta http-equiv="x-pjax-css-version" content="b7a4653359baeee3d827ca91d7c149e4962234557341efae58fad4aa5ce82a0a" data-turbo-track="reload">
+<meta http-equiv="x-pjax-js-version" content="1227e627b67675fc9295633fd1d1371dcc43ba2a9694c3e693203f40ab5452fa" data-turbo-track="reload">
+<meta name="turbo-cache-control" content="no-preview" data-turbo-transient="">
+<meta name="turbo-cache-control" content="no-cache" data-turbo-transient>
+<meta data-hydrostats="publish">
+<meta name="go-import" content="github.com/govalues/decimal git https://github.com/govalues/decimal.git">
+<meta name="octolytics-dimension-user_id" content="126001139" />
+<meta name="octolytics-dimension-user_login" content="govalues" />
+<meta name="octolytics-dimension-repository_id" content="612754668" />
+<meta name="octolytics-dimension-repository_nwo" content="govalues/decimal" />
+<meta name="octolytics-dimension-repository_public" content="true" />
+<meta name="octolytics-dimension-repository_is_fork" content="false" />
+<meta name="octolytics-dimension-repository_network_root_id" content="612754668" />
+<meta name="octolytics-dimension-repository_network_root_nwo" content="govalues/decimal" />
+<meta name="turbo-body-classes" content="logged-out env-production page-responsive">
+<meta name="disable-turbo" content="false">
+<meta name="browser-stats-url" content="https://api.github.com/_private/browser/stats">
+<meta name="browser-errors-url" content="https://api.github.com/_private/browser/errors">
+<meta name="release" content="e3cc4f8cef1bbe2e59e8b125a81fe519d96015e2" data-turbo-track="reload">
+<meta name="ui-target" content="full">
+<link rel="mask-icon" href="https://github.githubassets.com/assets/pinned-octocat-093da3e6fa40.svg" color="#000000">
+<link rel="alternate icon" class="js-site-favicon" type="image/png" href="https://github.githubassets.com/favicons/favicon.png">
+<link rel="icon" class="js-site-favicon" type="image/svg+xml" href="https://github.githubassets.com/favicons/favicon.svg" data-base-href="https://github.githubassets.com/favicons/favicon">
+<meta name="theme-color" content="#1e2327">
+<meta name="color-scheme" content="light dark" />
+<link rel="manifest" href="/manifest.json" crossOrigin="use-credentials">
+</head>
+<body class="logged-out env-production page-responsive" style="word-wrap: break-word;" >
+<div data-turbo-body class="logged-out env-production page-responsive" style="word-wrap: break-word;" >
+<div id="__primerPortalRoot__" style="z-index: 1000; position: absolute; width: 100%;" data-turbo-permanent>
+</div>
+<div class="position-relative header-wrapper js-header-wrapper ">
+<a href="#start-of-content" data-skip-target-assigned="false" class="px-2 tmp-py-4 color-bg-accent-emphasis color-fg-on-emphasis show-on-focus js-skip-to-content">Skip to content</a>
+<span data-view-component="true" class="progress-pjax-loader Progress position-fixed width-full">
+<span style="width: 0%;" data-view-component="true" class="Progress-item progress-pjax-loader-bar left-0 top-0 color-bg-accent-emphasis">
+</span>
+</span>
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/30201-57c73cd53e57ec6a.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/keyboard-shortcuts-dialog-b9b4218a1512b455.js" fetchpriority="low" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/primer-react-css.2489a3d4426b28d3.module.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/keyboard-shortcuts-dialog.d01096e6d41f9919.module.css" />
+<react-partial
+  partial-name="keyboard-shortcuts-dialog"
+  data-ssr="false"
+  data-attempted-ssr="false"
+  data-react-profiling="false"
+>
+<script type="application/json" data-target="react-partial.embeddedData">{"props":{"docsUrl":"https://docs.github.com/get-started/accessibility/keyboard-shortcuts"}}</script>
+<div data-target="react-partial.reactRoot">
+</div>
+</react-partial>
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/28052-948121aab0837bb7.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/315-41a95191752f4a55.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/71236-e2d5e8326b644be4.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/72388-94b4afaeb2a8e5ba.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/48129-83d8fafa2f4a17fa.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/44650-9e3583f09b45b865.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/6795-d3cd52656f429bdd.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/lazy-react-partial-marketing-header-a9133fb27123d69a.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/marketing-header-650354eae73e0e48.js" fetchpriority="low" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/primer-react-css.2489a3d4426b28d3.module.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/primer-react-brand-css.d7bf4cd1af1bdba4.module.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/lazy-react-partial-marketing-header.34c48846361e9495.module.css" />
+<react-partial
+  partial-name="marketing-header"
+  data-ssr="true"
+  data-attempted-ssr="true"
+  data-react-profiling="false"
+>
+<script type="application/json" data-target="react-partial.embeddedData">{"props":{"color_mode":"dark","logged_in":false,"marketing_page":false,"home_path":"/","login_path":"/login?return_to=https%3A%2F%2Fgithub.com%2Fgovalues%2Fdecimal%2Fblob%2Fmain%2Fdecimal.go","signup_path":"/signup?ref_cta=Sign+up\u0026ref_loc=header+logged+out\u0026ref_page=%2F%3Cuser-name%3E%2F%3Crepo-name%3E%2Fblob%2Fshow\u0026source=header-repo\u0026source_repo=govalues%2Fdecimal","signup_enabled":true,"is_signup_controller":false,"show_search_and_nav":true,"hide_search":false,"private_mode_enabled":false,"should_use_dotcom_links":true,"auth_hydro_click":"{\"event_type\":\"authentication.click\",\"payload\":{\"location_in_page\":\"site header menu\",\"repository_id\":null,\"auth_type\":\"SIGN_UP\",\"originating_url\":\"https://github.com/govalues/decimal/blob/main/decimal.go\",\"user_id\":null}}","auth_hydro_click_hmac":"e1cf7823130ced687beda8569f5c34622e37e9fae69729e0dcdde49dfaff1aa2","overlay":false,"fixed":false}}</script>
+<div data-target="react-partial.reactRoot">
+<div data-color-mode="dark" data-light-theme="light" data-dark-theme="dark">
+<header class="MarketingHeader-module__root__Tk7n3 HeaderMktg header-logged-out" role="banner" data-marketing-header="true" data-color-mode="dark" data-light-theme="light" data-dark-theme="dark" data-is-top="true">
+<h2 class="MarketingHeader-module__visuallyHidden__sqKsl">Navigation Menu</h2>
+<button type="button" class="MarketingHeader-module__backdrop__sw4RU" aria-label="Close navigation menu">
+</button>
+<div class="MarketingHeader-module__bar__mBSyE">
+<div class="MarketingHeader-module__topRow__yeury">
+<div class="MarketingHeader-module__toggleSlot__hDxbh">
+<button type="button" class="HeaderMenuToggle-module__toggle__i8EiC" aria-label="Toggle navigation" aria-expanded="false">
+<span class="HeaderMenuToggle-module__toggleBar__jVN0H">
+</span>
+<span class="HeaderMenuToggle-module__toggleBar__jVN0H">
+</span>
+<span class="HeaderMenuToggle-module__toggleBar__jVN0H">
+</span>
+</button>
+</div>
+<a href="/" aria-label="Homepage" class="HeaderLogo-module__logo__UFyHI" data-analytics-event="{&quot;action&quot;:&quot;homepage&quot;,&quot;tag&quot;:&quot;link&quot;,&quot;context&quot;:&quot;logo&quot;,&quot;location&quot;:&quot;header&quot;,&quot;label&quot;:&quot;homepage_link_logo_header&quot;}">
+<svg data-component="Octicon" aria-hidden="true" focusable="false" class="octicon octicon-mark-github" viewBox="0 0 24 24" width="32" height="32" fill="currentColor" display="inline-block" overflow="visible" style="vertical-align:text-bottom">
+<path d="M10.226 17.284c-2.965-.36-5.054-2.493-5.054-5.256 0-1.123.404-2.336 1.078-3.144-.292-.741-.247-2.314.09-2.965.898-.112 2.111.36 2.83 1.01.853-.269 1.752-.404 2.853-.404 1.1 0 1.999.135 2.807.382.696-.629 1.932-1.1 2.83-.988.315.606.36 2.179.067 2.942.72.854 1.101 2 1.101 3.167 0 2.763-2.089 4.852-5.098 5.234.763.494 1.28 1.572 1.28 2.807v2.336c0 .674.561 1.056 1.235.786 4.066-1.55 7.255-5.615 7.255-10.646C23.5 6.188 18.334 1 11.978 1 5.62 1 .5 6.188.5 12.545c0 4.986 3.167 9.12 7.435 10.669.606.225 1.19-.18 1.19-.786V20.63a2.9 2.9 0 0 1-1.078.224c-1.483 0-2.359-.808-2.987-2.313-.247-.607-.517-.966-1.034-1.033-.27-.023-.359-.135-.359-.27 0-.27.45-.471.898-.471.652 0 1.213.404 1.797 1.235.45.651.921.943 1.483.943.561 0 .92-.202 1.437-.719.382-.381.674-.718.944-.943">
+</path>
+</svg>
+</a>
+<div class="AuthCTAs-module__mobileActions__NNzeV">
+<a class="Primer_Brand__Button-module__Button___scH9Z Primer_Brand__Button-module__Button--subtle___F7pEE Primer_Brand__Button-module__Button--size-small___zQrEw AuthCTAs-module__cta__WpwQq" href="/login?return_to=https%3A%2F%2Fgithub.com%2Fgovalues%2Fdecimal%2Fblob%2Fmain%2Fdecimal.go" data-analytics-event="{&quot;action&quot;:&quot;sign_in&quot;,&quot;tag&quot;:&quot;link&quot;,&quot;context&quot;:&quot;auth_cta&quot;,&quot;location&quot;:&quot;header&quot;,&quot;label&quot;:&quot;sign_in_link_auth_cta_header&quot;}" data-hydro-click="{&quot;event_type&quot;:&quot;authentication.click&quot;,&quot;payload&quot;:{&quot;location_in_page&quot;:&quot;site header menu&quot;,&quot;repository_id&quot;:null,&quot;auth_type&quot;:&quot;SIGN_UP&quot;,&quot;originating_url&quot;:&quot;https://github.com/govalues/decimal/blob/main/decimal.go&quot;,&quot;user_id&quot;:null}}" data-hydro-click-hmac="e1cf7823130ced687beda8569f5c34622e37e9fae69729e0dcdde49dfaff1aa2">
+<span class="Primer_Brand__Button-module__Button__text___ED0bX">
+<span class="Primer_Brand__Text-module__Text___XeGJJ Primer_Brand__Text-module__Text-font--mona-sans___a8XJD Primer_Brand__Text-module__Text--default___GhPh_ Primer_Brand__Text-module__Text--100___B2ueX Primer_Brand__Text-module__Text--weight-medium___qJKf_ Primer_Brand__Button-module__Button--label___qrkyz Primer_Brand__Button-module__Button--label-subtle___8ndWH">Sign in</span>
+</span>
+</a>
+<button class="Primer_Brand__Button-module__Button___scH9Z Primer_Brand__Button-module__Button--subtle___F7pEE Primer_Brand__Button-module__Button--size-small___zQrEw HeaderAppearanceSettings-module__trigger__hUheK" type="button" aria-haspopup="dialog" aria-labelledby="_R_3dd_">
+<span class="Primer_Brand__Button-module__Button__leading-visual___jjtTe" data-testid="Button-leading-visual">
+<svg data-component="Octicon" focusable="false" aria-hidden="true" class="octicon octicon-sliders Primer_Brand__Button-module__Button__icon-visual____qybb" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" display="inline-block" overflow="visible" style="vertical-align:text-bottom">
+<path d="M15 2.75a.75.75 0 0 1-.75.75h-4a.75.75 0 0 1 0-1.5h4a.75.75 0 0 1 .75.75Zm-8.5.75v1.25a.75.75 0 0 0 1.5 0v-4a.75.75 0 0 0-1.5 0V2H1.75a.75.75 0 0 0 0 1.5H6.5Zm1.25 5.25a.75.75 0 0 0 0-1.5h-6a.75.75 0 0 0 0 1.5h6ZM15 8a.75.75 0 0 1-.75.75H11.5V10a.75.75 0 1 1-1.5 0V6a.75.75 0 0 1 1.5 0v1.25h2.75A.75.75 0 0 1 15 8Zm-9 5.25v-2a.75.75 0 0 0-1.5 0v1.25H1.75a.75.75 0 0 0 0 1.5H4.5v1.25a.75.75 0 0 0 1.5 0v-2Zm9 0a.75.75 0 0 1-.75.75h-6a.75.75 0 0 1 0-1.5h6a.75.75 0 0 1 .75.75Z">
+</path>
+</svg>
+</span>
+<span class="Primer_Brand__Button-module__Button__text___ED0bX">
+<span class="Primer_Brand__Text-module__Text___XeGJJ Primer_Brand__Text-module__Text-font--mona-sans___a8XJD Primer_Brand__Text-module__Text--default___GhPh_ Primer_Brand__Text-module__Text--100___B2ueX Primer_Brand__Text-module__Text--weight-medium___qJKf_ Primer_Brand__Button-module__Button--label___qrkyz Primer_Brand__Button-module__Button--label-subtle___8ndWH">
+</span>
+</span>
+</button>
+<div class="Primer_Brand__Tooltip-module__Tooltip___0Eipx" data-direction="s" aria-hidden="true" id="_R_3dd_">Appearance settings</div>
+</div>
+</div>
+<div class="MarketingHeader-module__menu__GIy3y">
+<div class="MarketingHeader-module__menuWrapper__owstH">
+<nav class="MarketingNavigation-module__nav__W0KYY" aria-label="Global">
+<ul class="MarketingNavigation-module__list__tFbMb">
+<li>
+<div class="NavDropdown-module__container__l2YeI">
+<button type="button" class="NavDropdown-module__button__PEHWX" aria-expanded="false" aria-controls="_R_nd_">Platform<svg data-component="Octicon" aria-hidden="true" focusable="false" class="octicon octicon-triangle-right NavDropdown-module__buttonIcon__Tkl8_" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" display="inline-block" overflow="visible" style="vertical-align:text-bottom">
+<path d="m6.427 4.427 3.396 3.396a.25.25 0 0 1 0 .354l-3.396 3.396A.25.25 0 0 1 6 11.396V4.604a.25.25 0 0 1 .427-.177Z">
+</path>
+</svg>
+</button>
+<div id="_R_nd_" class="NavDropdown-module__dropdown__xm1jd">
+<ul class="NavDropdown-module__list__zuCgG">
+<li>
+<div class="NavGroup-module__group__W8SqJ">
+<span class="Primer_Brand__Text-module__Text___XeGJJ Primer_Brand__Text-module__Text-font--monospace___QXHDQ Primer_Brand__Text-module__Text--muted___rE6mh Primer_Brand__Text-module__Text--100___B2ueX Primer_Brand__Text-module__Text--weight-medium___qJKf_ NavGroup-module__title__Wzxz2" id="_R_5knd_">AI CODE CREATION</span>
+<ul class="NavGroup-module__list__UCOFy" aria-labelledby="_R_5knd_">
+<li>
+<a class="Primer_Brand__Link-module__Link___lF11y Primer_Brand__Link-module__Link--default___VRVW0" href="https://github.com/features/copilot" data-analytics-event="{&quot;action&quot;:&quot;github_copilot&quot;,&quot;tag&quot;:&quot;link&quot;,&quot;context&quot;:&quot;platform&quot;,&quot;location&quot;:&quot;navbar&quot;,&quot;label&quot;:&quot;github_copilot_link_platform_navbar&quot;}">
+<span class="Primer_Brand__Text-module__Text___XeGJJ Primer_Brand__Text-module__Text-font--mona-sans___a8XJD Primer_Brand__Text-module__Text--default___GhPh_ Primer_Brand__Text-module__Text--200____P1wy Primer_Brand__Text-module__Text--antialiased___TYoXS Primer_Brand__Link-module__Link--label___jM8Ty">
+<span class="Primer_Brand__Text-module__Text___XeGJJ Primer_Brand__Text-module__Text-font--mona-sans___a8XJD Primer_Brand__Text-module__Text--default___GhPh_ Primer_Brand__Text-module__Text--200____P1wy Primer_Brand__Text-module__Text--antialiased___TYoXS Primer_Brand__Text-module__Text--weight-medium___qJKf_ NavLink-module__title__Q7t0p">
+<svg data-component="Octicon" aria-hidden="true" focusable="false" class="octicon octicon-copilot NavLink-module__icon__ltGNM" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" display="inline-block" overflow="visible" style="vertical-align:text-bottom">
+<path d="M7.998 15.035c-4.562 0-7.873-2.914-7.998-3.749V9.338c.085-.628.677-1.686 1.588-2.065.013-.07.024-.143.036-.218.029-.183.06-.384.126-.612-.201-.508-.254-1.084-.254-1.656 0-.87.128-1.769.693-2.484.579-.733 1.494-1.124 2.724-1.261 1.206-.134 2.262.034 2.944.765.05.053.096.108.139.165.044-.057.094-.112.143-.165.682-.731 1.738-.899 2.944-.765 1.23.137 2.145.528 2.724 1.261.566.715.693 1.614.693 2.484 0 .572-.053 1.148-.254 1.656.066.228.098.429.126.612.012.076.024.148.037.218.924.385 1.522 1.471 1.591 2.095v1.872c0 .766-3.351 3.795-8.002 3.795Zm0-1.485c2.28 0 4.584-1.11 5.002-1.433V7.862l-.023-.116c-.49.21-1.075.291-1.727.291-1.146 0-2.059-.327-2.71-.991A3.222 3.222 0 0 1 8 6.303a3.24 3.24 0 0 1-.544.743c-.65.664-1.563.991-2.71.991-.652 0-1.236-.081-1.727-.291l-.023.116v4.255c.419.323 2.722 1.433 5.002 1.433ZM6.762 2.83c-.193-.206-.637-.413-1.682-.297-1.019.113-1.479.404-1.713.7-.247.312-.369.789-.369 1.554 0 .793.129 1.171.308 1.371.162.181.519.379 1.442.379.853 0 1.339-.235 1.638-.54.315-.322.527-.827.617-1.553.117-.935-.037-1.395-.241-1.614Zm4.155-.297c-1.044-.116-1.488.091-1.681.297-.204.219-.359.679-.242 1.614.091.726.303 1.231.618 1.553.299.305.784.54 1.638.54.922 0 1.28-.198 1.442-.379.179-.2.308-.578.308-1.371 0-.765-.123-1.242-.37-1.554-.233-.296-.693-.587-1.713-.7Z">
+</path>
+<path d="M6.25 9.037a.75.75 0 0 1 .75.75v1.501a.75.75 0 0 1-1.5 0V9.787a.75.75 0 0 1 .75-.75Zm4.25.75v1.501a.75.75 0 0 1-1.5 0V9.787a.75.75 0 0 1 1.5 0Z">
+</path>
+</svg>GitHub Copilot</span>
+<span class="Primer_Brand__Text-module__Text___XeGJJ Primer_Brand__Text-module__Text-font--mona-sans___a8XJD Primer_
+
+[NOTE: this saved copy holds the first 46,076 characters of a 1,013,200-character document — the rest could not be delivered in one step. What is below is exact; what is missing is missing. If the part you need is not here, fetch the specific section of the page directly rather than assuming it is absent.]
\ No newline at end of file
diff --git a/tmp/reference/github.com_govalues_decimal_blob_main_quantize.go.txt b/tmp/reference/github.com_govalues_decimal_blob_main_quantize.go.txt
new file mode 100644
index 0000000..eb23b89
--- /dev/null
+++ b/tmp/reference/github.com_govalues_decimal_blob_main_quantize.go.txt
@@ -0,0 +1,346 @@
+
+
+
+
+  
+
+<!DOCTYPE html>
+<html
+  lang="en"
+  
+  data-color-mode="auto" data-light-theme="light" data-dark-theme="dark"
+  data-a11y-animated-images="system" data-a11y-link-underlines="true"
+  
+  >
+<head>
+<meta charset="utf-8">
+<link rel="dns-prefetch" href="https://github.githubassets.com">
+<link rel="dns-prefetch" href="https://avatars.githubusercontent.com">
+<link rel="dns-prefetch" href="https://github-cloud.s3.amazonaws.com">
+<link rel="dns-prefetch" href="https://user-images.githubusercontent.com/">
+<link rel="preconnect" href="https://github.githubassets.com" crossorigin>
+<link rel="preconnect" href="https://avatars.githubusercontent.com">
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/light-99f877e9ddfc0e51.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/light_high_contrast-48fdd0811afbab3c.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/dark-79ad2ace604703b3.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/dark_high_contrast-24484a076f02295f.css" />
+<link data-color-theme="light" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/light-99f877e9ddfc0e51.css" />
+<link data-color-theme="light_high_contrast" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/light_high_contrast-48fdd0811afbab3c.css" />
+<link data-color-theme="light_colorblind" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/light_colorblind-f4bf1142976e4bbf.css" />
+<link data-color-theme="light_colorblind_high_contrast" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/light_colorblind_high_contrast-f661b49995ba0bd8.css" />
+<link data-color-theme="light_tritanopia" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/light_tritanopia-0b38d22346321c92.css" />
+<link data-color-theme="light_tritanopia_high_contrast" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/light_tritanopia_high_contrast-f1c62c9e70259b9f.css" />
+<link data-color-theme="dark" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/dark-79ad2ace604703b3.css" />
+<link data-color-theme="dark_high_contrast" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/dark_high_contrast-24484a076f02295f.css" />
+<link data-color-theme="dark_colorblind" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/dark_colorblind-f50cacf0a86b9929.css" />
+<link data-color-theme="dark_colorblind_high_contrast" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/dark_colorblind_high_contrast-e61d4f4ca17852c2.css" />
+<link data-color-theme="dark_tritanopia" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/dark_tritanopia-39c10993d5603fac.css" />
+<link data-color-theme="dark_tritanopia_high_contrast" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/dark_tritanopia_high_contrast-73236c840c0c7d90.css" />
+<link data-color-theme="dark_dimmed" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/dark_dimmed-0de76f07cc035b10.css" />
+<link data-color-theme="dark_dimmed_high_contrast" crossorigin="anonymous" media="all" rel="stylesheet" data-href="https://github.githubassets.com/assets/dark_dimmed_high_contrast-fd1500c8744e40d6.css" />
+<style type="text/css">
+    :root {
+      --tab-size-preference: 4;
+    }
+
+    pre, code {
+      tab-size: var(--tab-size-preference);
+    }
+  </style>
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/primer-primitives-ed9ca172356fd545.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/primer-1d2c7f7b52a6068b.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/global-adcabba7b5c5d221.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/github-552513ad07a183a1.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/repository-11ee8a031c040c1a.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/code-2d56bdb0166c0238.css" />
+<script type="application/json" id="client-env">{"locale":"en","featureFlags":["actions_enable_background_steps","activity_diff_file_tree","activity_repos_file_tree","activity_repos_overview_header","activity_repos_overview_sidebar","agent_author_search_expansion","agent_author_search_expansion_ui_pulls","alternate_user_config_repo","billing_billable_licenses_cost_center_bucket_fix","billing_cost_center_list_assigned_resources","billing_cost_center_user_level_budgets","billing_discount_threshold_notification","billing_multi_user_cost_center_total_user_count","billing_user_level_budgets","billing_user_level_budgets_manage","block_user_close_content","ccr_files_changed_model_picker","ccr_mcp_skills_ga","code_quality_enablement_banner_targeting","code_quality_new_repo_selection_card","code_quality_org_level_trends","code_quality_remove_preview","code_view_raf_sticky_lines","codespaces_prebuild_region_target_update","coding_agent_create_task_strip","coding_agent_third_party_model_ui","contentful_primer_code_blocks","copilot_agent_snippy","copilot_api_agentic_issue_marshal_yaml","copilot_automations_pagination","copilot_chat_attach_multiple_images","copilot_chat_auto_mode_picker_paid","copilot_chat_category_rate_limit_messages","copilot_chat_clear_model_selection_for_default_change","copilot_chat_compact_tables","copilot_chat_docked_panel","copilot_chat_enable_tool_call_logs","copilot_chat_header_reorder","copilot_chat_input_commands","copilot_chat_interspersed_tool_calls","copilot_chat_max_upsell","copilot_chat_minimize_contextual","copilot_chat_model_picker_promotions","copilot_chat_models_browser_cache","copilot_chat_new_topic_nudge","copilot_chat_opening_thread_switch","copilot_chat_reduce_quota_checks","copilot_chat_vision_dotcom_chat_ga_gate","copilot_chat_vision_in_claude","copilot_chat_vision_preview_gate","copilot_cli_install_cta_max_plan","copilot_css_textarea_autosize","copilot_custom_copilots","copilot_custom_copilots_feature_preview","copilot_diff_explain_conversation_intent","copilot_diff_reference_context","copilot_duplicate_thread","copilot_extensions_removal_on_marketplace","copilot_fix_failed_workflows_all_skus","copilot_ftp_hyperspace_upgrade_prompt","copilot_hide_hovercard","copilot_immersive_code_block_transition_wrap","copilot_immersive_embedded_deferred_payload","copilot_immersive_embedded_draggable","copilot_immersive_embedded_header_button","copilot_immersive_embedded_implicit_references","copilot_immersive_embedded_skip_copilot_api_token_for_dotcom_context","copilot_immersive_file_block_transition_open","copilot_immersive_file_preview_keep_mounted","copilot_immersive_suggestion_pills","copilot_immersive_task_hyperlinking","copilot_immersive_task_within_chat_thread","copilot_mc_cli_resume_any_users_task","copilot_mission_control_agent_merge_fix_ci","copilot_mission_control_agent_merge_resolve_conflicts","copilot_mission_control_agent_merge_respond_to_reviewers","copilot_mission_control_early_stop","copilot_mission_control_environment_list_icons","copilot_mission_control_managed_sandbox_environments","copilot_mission_control_needs_attention","copilot_mission_control_reasoning_effort","copilot_mission_control_sandbox_remote_bypass","copilot_mission_control_session_filters","copilot_mission_control_task_alive_updates","copilot_mission_control_task_sharing","copilot_org_policy_page_focus_mode","copilot_pr_chat_enhancements","copilot_prominent_upgrade_button","copilot_resource_panel","copilot_settings_validation_ui","copilot_share_active_subthread","copilot_spaces_ga","copilot_spaces_individual_policies_ga","copilot_spark_handle_nil_friendly_name","copilot_swe_agent_authorization_status_ui","copilot_swe_agent_hide_model_picker_if_only_auto","copilot_swe_agent_issue_comment_trigger","copilot_swe_agent_pr_comment_model_picker","copilot_swe_agent_pull_request_comment_trigger","copilot_swe_agent_pull_request_merged_trigger","copilot_swe_agent_pull_request_opened_trigger","copilot_swe_agent_pull_request_synchronize_trigger","copilot_swe_agent_use_subagents","copilot_task_api_github_rest_style","copilot_token_based_billing","copilot_unconfigured_is_inherited","copilot_user_can_upgrade_plan_field","copilot_workbench_sunset","copilot_workbench_ubb","dashboard_indexeddb_caching","dashboard_lists_max_age_filter","dashboard_surface_persistent_preferences","dashboard_universe_2025_feedback_dialog","dependencies_picker_tanstack","flex_cta_groups_mvp","flex_suite_details","flex_suite_disable_river_accordion_dither","ga_enterprise_teams_ui","glc_code_quality_repo_settings_workflow_config","global_nav_react","hide_github_models_ui","hyperspace_2025_logged_out_batch_1","hyperspace_2025_logged_out_batch_2","hyperspace_2025_logged_out_batch_3","in_product_messaging_datadog_monitoring","ipm_global_transactional_message_copilot","ipm_global_transactional_message_issues","ipm_global_transactional_message_prs","ipm_global_transactional_message_repos","ipm_global_transactional_message_spaces","issue_fields_multi_select","issue_inline_avatars","issue_pinned_views","issue_pinned_views_optimistic_updates","issue_relative_time_micro","issue_viewer_subissues_optimistic_overlay","issues_dashboard_sso_structured_errors","issues_expanded_file_types","issues_hide_closed_sub_issues","issues_lazy_load_comment_box_suggestions","issues_react_chrome_container_query_fix","labels_archiving","labels_archiving_info","landing_pages_ninetailed","landing_pages_web_vitals_tracking","lifecycle_label_name_updates","marketing_pages_search_explore_provider","memex_default_issue_create_repository","memex_lazy_hydrate_agent_tasks","memex_live_update_hovercard","memex_mwl_filter_field_delimiter","memex_remove_deprecated_type_issue","merge_queue_restricted_pushers_warning","merge_status_checks_refetch_dedupe","merge_status_header_feedback","new_quick_search_dotcom","oauth_authorize_clickjacking_protection","octocaptcha_origin_optimization","org_repos_filtered_list_layout","primer_react_css_anchor_positioning","primer_react_merged_forwarded_refs","property_definition_empty_state_suggestions","prs_copilot_app_open_action","prs_css_anchor_positioning","pull_request_copilot_attribution_header","pull_request_overview_panel_edit_description","pull_request_stacks_feedback_dialog","pull_request_virtualization_image_estimate","pull_request_virtualization_scroll_compensation","pull_request_virtualization_scroll_intent","react_blob_isolate_code_lines","react_blob_ssr_content_visibility","react_data_router_tanstack_allowed","react_sandbox_future_tanstack","repo_issues_sidebar_layout","repo_overview_ask_copilot","repos_contributors_limited_default_range","repos_finder_sidebar_layout","review_involves_filter","rule_ignored_file_paths","rulesets_actor_list_editor","sample_network_conn_type","secret_scanning_pattern_alerts_link","security_center_artifact_filters_popover","see_who_reacted","semantic_similarity_duplicate_issue_detection","session_logs_ungroup_reasoning_text","site_banner_desktop_copilot_app","site_code_quality_page","site_ghca_pixel_mona","site_github_app_ga_page","site_github_app_ga_page_highlight","site_global_banner_deprecate_spark","site_global_banner_dev_days_organizer","site_global_nav_spark_models_removed","spark_prompt_secret_scanning","spark_server_connection_status","suppress_automated_browser_vitals","swp_forms_disable_octocaptcha","thread_resolution_reason","update_issue_suggestions","viewscreen_sandbox","warn_inaccessible_attachments","webp_support","workbench_store_readonly"],"copilotApiOverrideUrl":"https://api.githubcopilot.com","cmcApiUrl":"https://api.github.com/cmc_internal/api"}</script>
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/high-contrast-cookie-700cb8fd7174aa98.js">
+</script>
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/wp-runtime-1ae46977f3fcd063.js" defer="defer">
+</script>
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/app-foundation-4437307b8f9d7771.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/app-runtime-8365b7f9078f5299.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/fetch-utilities-8fe90c8c85b950d2.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/78205-6cf07db9c71bd767.js" />
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/environment-753af45350854edc.js" defer="defer">
+</script>
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/app-runtime.4edc00cd7dcee842.module.css" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/catalyst-38077bb411140672.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/selector-observer-2649f99b2f1a6405.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/relative-time-element-c21b72dfe6bab348.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/296-2e18342b802e67d2.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/816-41f1bbf5693911e3.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/65637-cd80fa0f84afe946.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/58494-bbf2743f411af058.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/31721-0ef53b2f96a19876.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/46740-90376e604f852814.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/98944-57d83b43eefe5ac0.js" />
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/github-elements-29bb1ba9dbea3e72.js" defer="defer">
+</script>
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/element-registry-698015ad7251500e.js" defer="defer">
+</script>
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/runtime-helpers-fc37f5662f7833a3.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/aria-live-7d7a9fdad5f85d01.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/hotkey-1cb8fabe6be5aae6.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/react-core-29d04a3ce0e60b2e.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/react-lib-94319d819a6168f4.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/50841-2b0631b45aaf5408.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/2761-b7a9419af18b3168.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/88475-1ef5f4960149f37f.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/26533-677fb085023d4883.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/3609-aeb65154451d2df4.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/87644-a4a8bf1e50c8f268.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/39448-1ea76084e5b8e2e3.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/54130-e4c7ec7528d1f04f.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/1741-19fd38c1c119f0b9.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/64923-fd55cab179c0991d.js" />
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/behaviors-a3f1bb7c13f92841.js" defer="defer">
+</script>
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/react-core.0027ad4d227604b8.module.css" />
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/code-menu-1080af005f56a9b7.js" defer="defer">
+</script>
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/wp-runtime-1ae46977f3fcd063.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/primer-react-3f5e80eddfe4fa83.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/76256-4c9ade0d3ba0f30e.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/437-866d9a255948fbf8.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/2927-a89925c2c122f0b3.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/13365-afa40f59b2c1ae40.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/7463-c01d2638c7d87a79.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/82065-d83c3301556505f1.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/27600-87c6894442ac9f57.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/60033-ac83dfbacec0c384.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/14646-c29030274d61aca2.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/11294-5b8577f6bc988a82.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/89138-de750ac7185aeec4.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/90329-c7b3cf6214d8d577.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/55903-91e88e62460bae56.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/52383-a696842abacedd89.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/12300-b13e9eea6cc191a1.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/33083-5bfc3e419dbd3b4e.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/24254-e76bb3d4c66c3f3d.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/84661-938e59aed66644bc.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/87051-f8838e5828c8d9bb.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/23989-9f2c58e6aedee694.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/64709-2f9885a1f72f966c.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/99666-e16732356424ef41.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/64015-c67854db64676d7d.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/23128-cc7fbe599e720ed4.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/50084-db237f60c1874138.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/110-c337c3fc77b06155.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/1181-7f30d30e96ecc14c.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/50006-8701d184da21a557.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/94789-9edb64f391499e63.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/819-3fb1e5106dc20469.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/22828-631ce697062c1b2c.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/53878-1d336962bed52509.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/20277-7c60be2a3b3c0a75.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/4596-aa474803d308d614.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/27080-4351f698d6cd6e4f.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/27555-36f6bd4ce4a97436.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/56403-fa8d4be074ee04dd.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/15923-13a155703619471d.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/24850-9388f10dac6609c3.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/20701-4b34a04737378d69.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/64834-2f9d36b071419dda.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/99412-65156a91f2f68057.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/dynamic-github-ui--code-view--route-components-0bfe7d06096adcbb.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/99388-2a6c421acaa902e8.js" />
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/code-view-fe012b4e27371812.js" defer="defer">
+</script>
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/primer-react-css.2489a3d4426b28d3.module.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/1181.1fe8862e00251654.module.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/4527.7acb62ab59e4bb7f.module.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/dynamic-github-ui--code-view--route-components.1b6e469b25b9a7e8.module.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/code-view.19a43f93b38c2e4c.module.css" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/7115-afcd35d1c4e62cd6.js" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/90694-9f0eb78486cddc72.js" />
+<script crossorigin="anonymous" type="module" src="https://github.githubassets.com/assets/notifications-subscriptions-menu-17d6dfef383e4fb4.js" defer="defer">
+</script>
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/primer-react-css.2489a3d4426b28d3.module.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/notifications-subscriptions-menu.f1a3f6ad7c62829f.module.css" />
+<title>File not found · GitHub</title>
+<meta name="route-pattern" content="/:user_id/:repository/blob/*name(/*path)" data-turbo-transient>
+<meta name="route-controller" content="blob" data-turbo-transient>
+<meta name="route-action" content="show" data-turbo-transient>
+<meta name="fetch-nonce" content="v2:bdadef4b-a764-1485-4b1e-1e0b7dcce437">
+<meta name="current-catalog-service-hash" content="f3abb0cc802f3d7b95fc8762b94bdcb13bf39634c40c357301c4aa1d67a256fb">
+<meta name="request-id" content="F270:F0176:D76A6:FA0F4:6A9204F7" data-pjax-transient="true"/>
+<meta name="html-safe-nonce" content="60ae67a186ba4cfead5f4cdde76d325404b1e57d674b38b00d59afa59b5e0526" data-pjax-transient="true"/>
+<meta name="visitor-payload" content="eyJyZWZlcnJlciI6IiIsInJlcXVlc3RfaWQiOiJGMjcwOkYwMTc2OkQ3NkE2OkZBMEY0OjZBOTIwNEY3IiwidmlzaXRvcl9pZCI6IjgyMDE4ODk3NTMyMDI4MjAzNDQiLCJyZWdpb25fZWRnZSI6InNvdXRoZWFzdGFzaWEiLCJyZWdpb25fcmVuZGVyIjoic291dGhlYXN0YXNpYSJ9" data-pjax-transient="true"/>
+<meta name="visitor-hmac" content="4e4e3731cde3cdc8a96af15ab1ca70f9765c4045c308226e8cc77f0f0afeaf2e" data-pjax-transient="true"/>
+<meta name="hovercard-subject-tag" content="repository:612754668" data-turbo-transient>
+<meta name="github-keyboard-shortcuts" content="repository,source-code,file-tree,copilot" data-turbo-transient="true" />
+<meta name="selected-link" value="/govalues/decimal/blob/main/quantize.go" data-turbo-transient>
+<link rel="assets" href="https://github.githubassets.com/">
+<meta name="google-site-verification" content="Apib7-x98H0j5cPqHWwSMm6dNU4GmODRoqxLiDzdx9I">
+<meta name="octolytics-url" content="https://collector.github.com/github/collect" />
+<meta name="analytics-location" content="/&lt;user-name&gt;/&lt;repo-name&gt;/blob/show" data-turbo-transient="true" />
+<meta name="user-login" content="">
+<meta name="viewport" content="width=device-width">
+<meta name="description" content="Correctly rounded decimals for Go. Contribute to govalues/decimal development by creating an account on GitHub.">
+<link rel="search" type="application/opensearchdescription+xml" href="/opensearch.xml" title="GitHub">
+<link rel="fluid-icon" href="https://github.com/fluidicon.png" title="GitHub">
+<meta property="fb:app_id" content="1401488693436528">
+<meta name="apple-itunes-app" content="app-id=1477376905, app-argument=https://github.com/govalues/decimal/blob/main/quantize.go" />
+<meta name="twitter:image" content="https://opengraph.githubassets.com/f2db899c8df4048cc0709e54917a24a42e46bd87c7d4c28ab77bc6482e0380eb/govalues/decimal" />
+<meta name="twitter:site" content="@github" />
+<meta name="twitter:card" content="summary_large_image" />
+<meta name="twitter:title" content="File not found · govalues/decimal" />
+<meta name="twitter:description" content="Correctly rounded decimals for Go. Contribute to govalues/decimal development by creating an account on GitHub." />
+<meta property="og:image" content="https://opengraph.githubassets.com/f2db899c8df4048cc0709e54917a24a42e46bd87c7d4c28ab77bc6482e0380eb/govalues/decimal" />
+<meta property="og:image:alt" content="Correctly rounded decimals for Go. Contribute to govalues/decimal development by creating an account on GitHub." />
+<meta property="og:image:width" content="1200" />
+<meta property="og:image:height" content="600" />
+<meta property="og:site_name" content="GitHub" />
+<meta property="og:type" content="object" />
+<meta property="og:title" content="File not found · govalues/decimal" />
+<meta property="og:url" content="https://github.com/govalues/decimal" />
+<meta property="og:description" content="Correctly rounded decimals for Go. Contribute to govalues/decimal development by creating an account on GitHub." />
+<meta name="hostname" content="github.com">
+<meta name="expected-hostname" content="github.com">
+<meta http-equiv="x-pjax-version" content="31ba3130fefdd2c1870d6b3163de2a095f1f1dfc52fb808692b26b6c5a527a80" data-turbo-track="reload">
+<meta http-equiv="x-pjax-csp-version" content="2af6a6627810d190be616096b617c8f37a1419b9435f76190f0e0d7638222ac1" data-turbo-track="reload">
+<meta http-equiv="x-pjax-css-version" content="b7a4653359baeee3d827ca91d7c149e4962234557341efae58fad4aa5ce82a0a" data-turbo-track="reload">
+<meta http-equiv="x-pjax-js-version" content="068f78dcc7704aa10c84c49b0b14214169995ba0b21663255024c72412cba1e0" data-turbo-track="reload">
+<meta name="turbo-cache-control" content="no-preview" data-turbo-transient="">
+<meta name="turbo-cache-control" content="no-cache" data-turbo-transient>
+<meta name="go-import" content="github.com/govalues/decimal git https://github.com/govalues/decimal.git">
+<meta name="octolytics-dimension-user_id" content="126001139" />
+<meta name="octolytics-dimension-user_login" content="govalues" />
+<meta name="octolytics-dimension-repository_id" content="612754668" />
+<meta name="octolytics-dimension-repository_nwo" content="govalues/decimal" />
+<meta name="octolytics-dimension-repository_public" content="true" />
+<meta name="octolytics-dimension-repository_is_fork" content="false" />
+<meta name="octolytics-dimension-repository_network_root_id" content="612754668" />
+<meta name="octolytics-dimension-repository_network_root_nwo" content="govalues/decimal" />
+<meta name="turbo-body-classes" content="logged-out env-production page-responsive">
+<meta name="disable-turbo" content="false">
+<meta name="browser-stats-url" content="https://api.github.com/_private/browser/stats">
+<meta name="browser-errors-url" content="https://api.github.com/_private/browser/errors">
+<meta name="release" content="3e7488c2456efa6a4a7f249907ec22e0d9f1da66" data-turbo-track="reload">
+<meta name="ui-target" content="full">
+<link rel="mask-icon" href="https://github.githubassets.com/assets/pinned-octocat-093da3e6fa40.svg" color="#000000">
+<link rel="alternate icon" class="js-site-favicon" type="image/png" href="https://github.githubassets.com/favicons/favicon.png">
+<link rel="icon" class="js-site-favicon" type="image/svg+xml" href="https://github.githubassets.com/favicons/favicon.svg" data-base-href="https://github.githubassets.com/favicons/favicon">
+<meta name="theme-color" content="#1e2327">
+<meta name="color-scheme" content="light dark" />
+<link rel="manifest" href="/manifest.json" crossOrigin="use-credentials">
+</head>
+<body class="logged-out env-production page-responsive" style="word-wrap: break-word;" >
+<div data-turbo-body class="logged-out env-production page-responsive" style="word-wrap: break-word;" >
+<div id="__primerPortalRoot__" style="z-index: 1000; position: absolute; width: 100%;" data-turbo-permanent>
+</div>
+<div class="position-relative header-wrapper js-header-wrapper ">
+<a href="#start-of-content" data-skip-target-assigned="false" class="px-2 tmp-py-4 color-bg-accent-emphasis color-fg-on-emphasis show-on-focus js-skip-to-content">Skip to content</a>
+<span data-view-component="true" class="progress-pjax-loader Progress position-fixed width-full">
+<span style="width: 0%;" data-view-component="true" class="Progress-item progress-pjax-loader-bar left-0 top-0 color-bg-accent-emphasis">
+</span>
+</span>
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/30201-57c73cd53e57ec6a.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/keyboard-shortcuts-dialog-51f3189fa2e46dce.js" fetchpriority="low" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/primer-react-css.2489a3d4426b28d3.module.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/keyboard-shortcuts-dialog.fdb50e622e968bca.module.css" />
+<react-partial
+  partial-name="keyboard-shortcuts-dialog"
+  data-ssr="false"
+  data-attempted-ssr="false"
+  data-react-profiling="false"
+>
+<script type="application/json" data-target="react-partial.embeddedData">{"props":{"docsUrl":"https://docs.github.com/get-started/accessibility/keyboard-shortcuts"}}</script>
+<div data-target="react-partial.reactRoot">
+</div>
+</react-partial>
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/28052-948121aab0837bb7.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/315-41a95191752f4a55.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/71236-e2d5e8326b644be4.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/72388-94b4afaeb2a8e5ba.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/48129-83d8fafa2f4a17fa.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/44650-9e3583f09b45b865.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/6795-d3cd52656f429bdd.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/lazy-react-partial-marketing-header-a9133fb27123d69a.js" fetchpriority="low" />
+<link crossorigin="anonymous" rel="modulepreload" href="https://github.githubassets.com/assets/marketing-header-f3f7f6eca7d9e812.js" fetchpriority="low" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/primer-react-css.2489a3d4426b28d3.module.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/primer-react-brand-css.d7bf4cd1af1bdba4.module.css" />
+<link crossorigin="anonymous" media="all" rel="stylesheet" href="https://github.githubassets.com/assets/lazy-react-partial-marketing-header.34c48846361e9495.module.css" />
+<react-partial
+  partial-name="marketing-header"
+  data-ssr="true"
+  data-attempted-ssr="true"
+  data-react-profiling="false"
+>
+<script type="application/json" data-target="react-partial.embeddedData">{"props":{"color_mode":"dark","logged_in":false,"marketing_page":false,"home_path":"/","login_path":"/login?return_to=https%3A%2F%2Fgithub.com%2Fgovalues%2Fdecimal%2Fblob%2Fmain%2Fquantize.go","signup_path":"/signup?ref_cta=Sign+up\u0026ref_loc=header+logged+out\u0026ref_page=%2F%3Cuser-name%3E%2F%3Crepo-name%3E%2Fblob%2Fshow\u0026source=header-repo\u0026source_repo=govalues%2Fdecimal","signup_enabled":true,"is_signup_controller":false,"show_search_and_nav":true,"hide_search":false,"private_mode_enabled":false,"should_use_dotcom_links":true,"auth_hydro_click":"{\"event_type\":\"authentication.click\",\"payload\":{\"location_in_page\":\"site header menu\",\"repository_id\":null,\"auth_type\":\"SIGN_UP\",\"originating_url\":\"https://github.com/govalues/decimal/blob/main/quantize.go\",\"user_id\":null}}","auth_hydro_click_hmac":"32a270077c0ef059991f6bd486485dc9db8298d314eb47709e34728a6c28a1f9","overlay":false,"fixed":false}}</script>
+<div data-target="react-partial.reactRoot">
+<div data-color-mode="dark" data-light-theme="light" data-dark-theme="dark">
+<header class="MarketingHeader-module__root__Tk7n3 HeaderMktg header-logged-out" role="banner" data-marketing-header="true" data-color-mode="dark" data-light-theme="light" data-dark-theme="dark" data-is-top="true">
+<h2 class="MarketingHeader-module__visuallyHidden__sqKsl">Navigation Menu</h2>
+<button type="button" class="MarketingHeader-module__backdrop__sw4RU" aria-label="Close navigation menu">
+</button>
+<div class="MarketingHeader-module__bar__mBSyE">
+<div class="MarketingHeader-module__topRow__yeury">
+<div class="MarketingHeader-module__toggleSlot__hDxbh">
+<button type="button" class="HeaderMenuToggle-module__toggle__i8EiC" aria-label="Toggle navigation" aria-expanded="false">
+<span class="HeaderMenuToggle-module__toggleBar__jVN0H">
+</span>
+<span class="HeaderMenuToggle-module__toggleBar__jVN0H">
+</span>
+<span class="HeaderMenuToggle-module__toggleBar__jVN0H">
+</span>
+</button>
+</div>
+<a href="/" aria-label="Homepage" class="HeaderLogo-module__logo__UFyHI" data-analytics-event="{&quot;action&quot;:&quot;homepage&quot;,&quot;tag&quot;:&quot;link&quot;,&quot;context&quot;:&quot;logo&quot;,&quot;location&quot;:&quot;header&quot;,&quot;label&quot;:&quot;homepage_link_logo_header&quot;}">
+<svg data-component="Octicon" aria-hidden="true" focusable="false" class="octicon octicon-mark-github" viewBox="0 0 24 24" width="32" height="32" fill="currentColor" display="inline-block" overflow="visible" style="vertical-align:text-bottom">
+<path d="M10.226 17.284c-2.965-.36-5.054-2.493-5.054-5.256 0-1.123.404-2.336 1.078-3.144-.292-.741-.247-2.314.09-2.965.898-.112 2.111.36 2.83 1.01.853-.269 1.752-.404 2.853-.404 1.1 0 1.999.135 2.807.382.696-.629 1.932-1.1 2.83-.988.315.606.36 2.179.067 2.942.72.854 1.101 2 1.101 3.167 0 2.763-2.089 4.852-5.098 5.234.763.494 1.28 1.572 1.28 2.807v2.336c0 .674.561 1.056 1.235.786 4.066-1.55 7.255-5.615 7.255-10.646C23.5 6.188 18.334 1 11.978 1 5.62 1 .5 6.188.5 12.545c0 4.986 3.167 9.12 7.435 10.669.606.225 1.19-.18 1.19-.786V20.63a2.9 2.9 0 0 1-1.078.224c-1.483 0-2.359-.808-2.987-2.313-.247-.607-.517-.966-1.034-1.033-.27-.023-.359-.135-.359-.27 0-.27.45-.471.898-.471.652 0 1.213.404 1.797 1.235.45.651.921.943 1.483.943.561 0 .92-.202 1.437-.719.382-.381.674-.718.944-.943">
+</path>
+</svg>
+</a>
+<div class="AuthCTAs-module__mobileActions__NNzeV">
+<a class="Primer_Brand__Button-module__Button___scH9Z Primer_Brand__Button-module__Button--subtle___F7pEE Primer_Brand__Button-module__Button--size-small___zQrEw AuthCTAs-module__cta__WpwQq" href="/login?return_to=https%3A%2F%2Fgithub.com%2Fgovalues%2Fdecimal%2Fblob%2Fmain%2Fquantize.go" data-analytics-event="{&quot;action&quot;:&quot;sign_in&quot;,&quot;tag&quot;:&quot;link&quot;,&quot;context&quot;:&quot;auth_cta&quot;,&quot;location&quot;:&quot;header&quot;,&quot;label&quot;:&quot;sign_in_link_auth_cta_header&quot;}" data-hydro-click="{&quot;event_type&quot;:&quot;authentication.click&quot;,&quot;payload&quot;:{&quot;location_in_page&quot;:&quot;site header menu&quot;,&quot;repository_id&quot;:null,&quot;auth_type&quot;:&quot;SIGN_UP&quot;,&quot;originating_url&quot;:&quot;https://github.com/govalues/decimal/blob/main/quantize.go&quot;,&quot;user_id&quot;:null}}" data-hydro-click-hmac="32a270077c0ef059991f6bd486485dc9db8298d314eb47709e34728a6c28a1f9">
+<span class="Primer_Brand__Button-module__Button__text___ED0bX">
+<span class="Primer_Brand__Text-module__Text___XeGJJ Primer_Brand__Text-module__Text-font--mona-sans___a8XJD Primer_Brand__Text-module__Text--default___GhPh_ Primer_Brand__Text-module__Text--100___B2ueX Primer_Brand__Text-module__Text--weight-medium___qJKf_ Primer_Brand__Button-module__Button--label___qrkyz Primer_Brand__Button-module__Button--label-subtle___8ndWH">Sign in</span>
+</span>
+</a>
+<button class="Primer_Brand__Button-module__Button___scH9Z Primer_Brand__Button-module__Button--subtle___F7pEE Primer_Brand__Button-module__Button--size-small___zQrEw HeaderAppearanceSettings-module__trigger__hUheK" type="button" aria-haspopup="dialog" aria-labelledby="_R_3dd_">
+<span class="Primer_Brand__Button-module__Button__leading-visual___jjtTe" data-testid="Button-leading-visual">
+<svg data-component="Octicon" focusable="false" aria-hidden="true" class="octicon octicon-sliders Primer_Brand__Button-module__Button__icon-visual____qybb" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" display="inline-block" overflow="visible" style="vertical-align:text-bottom">
+<path d="M15 2.75a.75.75 0 0 1-.75.75h-4a.75.75 0 0 1 0-1.5h4a.75.75 0 0 1 .75.75Zm-8.5.75v1.25a.75.75 0 0 0 1.5 0v-4a.75.75 0 0 0-1.5 0V2H1.75a.75.75 0 0 0 0 1.5H6.5Zm1.25 5.25a.75.75 0 0 0 0-1.5h-6a.75.75 0 0 0 0 1.5h6ZM15 8a.75.75 0 0 1-.75.75H11.5V10a.75.75 0 1 1-1.5 0V6a.75.75 0 0 1 1.5 0v1.25h2.75A.75.75 0 0 1 15 8Zm-9 5.25v-2a.75.75 0 0 0-1.5 0v1.25H1.75a.75.75 0 0 0 0 1.5H4.5v1.25a.75.75 0 0 0 1.5 0v-2Zm9 0a.75.75 0 0 1-.75.75h-6a.75.75 0 0 1 0-1.5h6a.75.75 0 0 1 .75.75Z">
+</path>
+</svg>
+</span>
+<span class="Primer_Brand__Button-module__Button__text___ED0bX">
+<span class="Primer_Brand__Text-module__Text___XeGJJ Primer_Brand__Text-module__Text-font--mona-sans___a8XJD Primer_Brand__Text-module__Text--default___GhPh_ Primer_Brand__Text-module__Text--100___B2ueX Primer_Brand__Text-module__Text--weight-medium___qJKf_ Primer_Brand__Button-module__Button--label___qrkyz Primer_Brand__Button-module__Button--label-subtle___8ndWH">
+</span>
+</span>
+</button>
+<div class="Primer_Brand__Tooltip-module__Tooltip___0Eipx" data-direction="s" aria-hidden="true" id="_R_3dd_">Appearance settings</div>
+</div>
+</div>
+<div class="MarketingHeader-module__menu__GIy3y">
+<div class="MarketingHeader-module__menuWrapper__owstH">
+<nav class="MarketingNavigation-module__nav__W0KYY" aria-label="Global">
+<ul class="MarketingNavigation-module__list__tFbMb">
+<li>
+<div class="NavDropdown-module__container__l2YeI">
+<button type="button" class="NavDropdown-module__button__PEHWX" aria-expanded="false" aria-controls="_R_nd_">Platform<svg data-component="Octicon" aria-hidden="true" focusable="false" class="octicon octicon-triangle-right NavDropdown-module__buttonIcon__Tkl8_" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" display="inline-block" overflow="visible" style="vertical-align:text-bottom">
+<path d="m6.427 4.427 3.396 3.396a.25.25 0 0 1 0 .354l-3.396 3.396A.25.25 0 0 1 6 11.396V4.604a.25.25 0 0 1 .427-.177Z">
+</path>
+</svg>
+</button>
+<div id="_R_nd_" class="NavDropdown-module__dropdown__xm1jd">
+<ul class="NavDropdown-module__list__zuCgG">
+<li>
+<div class="NavGroup-module__group__W8SqJ">
+<span class="Primer_Brand__Text-module__Text___XeGJJ Primer_Brand__Text-module__Text-font--monospace___QXHDQ Primer_Brand__Text-module__Text--muted___rE6mh Primer_Brand__Text-module__Text--100___B2ueX Primer_Brand__Text-module__Text--weight-medium___qJKf_ NavGroup-module__title__Wzxz2" id="_R_5knd_">AI CODE CREATION</span>
+<ul class="NavGroup-module__list__UCOFy" aria-labelledby="_R_5knd_">
+<li>
+<a class="Primer_Brand__Link-module__Link___lF11y Primer_Brand__Link-module__Link--default___VRVW0" href="https://github.com/features/copilot" data-analytics-event="{&quot;action&quot;:&quot;github_copilot&quot;,&quot;tag&quot;:&quot;link&quot;,&quot;context&quot;:&quot;platform&quot;,&quot;location&quot;:&quot;navbar&quot;,&quot;label&quot;:&quot;github_copilot_link_platform_navbar&quot;}">
+<span class="Primer_Brand__Text-module__Text___XeGJJ Primer_Brand__Text-module__Text-font--mona-sans___a8XJD Primer_Brand__Text-module__Text--default___GhPh_ Primer_Brand__Text-module__Text--200____P1wy Primer_Brand__Text-module__Text--antialiased___TYoXS Primer_Brand__Link-module__Link--label___jM8Ty">
+<span class="Primer_Brand__Text-module__Text___XeGJJ Primer_Brand__Text-module__Text-font--mona-sans___a8XJD Primer_Brand__Text-module__Text--default___GhPh_ Primer_Brand__Text-module__Text--200____P1wy Primer_Brand__Text-module__Text--antialiased___TYoXS Primer_Brand__Text-module__Text--weight-medium___qJKf_ NavLink-module__title__Q7t0p">
+<svg data-component="Octicon" aria-hidden="true" focusable="false" class="octicon octicon-copilot NavLink-module__icon__ltGNM" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" display="inline-block" overflow="visible" style="vertical-align:text-bottom">
+<path d="M7.998 15.035c-4.562 0-7.873-2.914-7.998-3.749V9.338c.085-.628.677-1.686 1.588-2.065.013-.07.024-.143.036-.218.029-.183.06-.384.126-.612-.201-.508-.254-1.084-.254-1.656 0-.87.128-1.769.693-2.484.579-.733 1.494-1.124 2.724-1.261 1.206-.134 2.262.034 2.944.765.05.053.096.108.139.165.044-.057.094-.112.143-.165.682-.731 1.738-.899 2.944-.765 1.23.137 2.145.528 2.724 1.261.566.715.693 1.614.693 2.484 0 .572-.053 1.148-.254 1.656.066.228.098.429.126.612.012.076.024.148.037.218.924.385 1.522 1.471 1.591 2.095v1.872c0 .766-3.351 3.795-8.002 3.795Zm0-1.485c2.28 0 4.584-1.11 5.002-1.433V7.862l-.023-.116c-.49.21-1.075.291-1.727.291-1.146 0-2.059-.327-2.71-.991A3.222 3.222 0 0 1 8 6.303a3.24 3.24 0 0 1-.544.743c-.65.664-1.563.991-2.71.991-.652 0-1.236-.081-1.727-.291l-.023.116v4.255c.419.323 2.722 1.433 5.002 1.433ZM6.762 2.83c-.193-.206-.637-.413-1.682-.297-1.019.113-1.479.404-1.713.7-.247.312-.369.789-.369 1.554 0 .793.129 1.171.308 1.371.162.181.519.379 1.442.379.853 0 1.339-.235 1.638-.54.315-.322.527-.827.617-1.553.117-.935-.037-1.395-.241-1.614Zm4.155-.297c-1.044-.116-1.488.091-1.681.297-.204.219-.359.679-.242 1.614.091.726.303 1.231.618 1.553.299.305.784.54 1.638.54.922 0 1.28-.198 1.442-.379.179-.2.308-.578.308-1.371 0-.765-.123-1.242-.37-1.554-.233-.296-.693-.587-1.713-.7Z">
+</path>
+<path d="M6.25 9.037a.75.75 0 0 1 .75.75v1.501a.75.75 0 0 1-1.5 0V9.787a.75.75 0 0 1 .75-.75Zm4.25.75v1.501a.75.75 0 0 1-1.5 0V9.787a.75.75 0 0 1 1.5 0Z">
+</path>
+</svg>GitHub Copilot</span>
+<span class="Primer_Brand__Text-module__Text___XeGJJ Primer_Brand__Text-module__Text-font--mona-sans___a8XJD Primer_Brand__Text-module__Text--muted___rE6mh Primer_Brand__Text-module__Text--200____P1
+
+[NOTE: this saved copy holds the first 46,077 characters of a 193,706-character document — the rest could not be delivered in one step. What is below is exact; what is missing is missing. If the part you need is not here, fetch the specific section of the page directly rather than assuming it is absent.]
\ No newline at end of file
diff --git a/tmp/reference/raw.githubusercontent.com_govalues_decimal_main_decimal.go.txt b/tmp/reference/raw.githubusercontent.com_govalues_decimal_main_decimal.go.txt
new file mode 100644
index 0000000..90166ed
--- /dev/null
+++ b/tmp/reference/raw.githubusercontent.com_govalues_decimal_main_decimal.go.txt
@@ -0,0 +1,1695 @@
+package decimal
+
+import (
+	"database/sql/driver"
+	"errors"
+	"fmt"
+	"math"
+	"strconv"
+	"unsafe"
+)
+
+// Decimal represents a finite floating-point decimal number.
+// Its zero value corresponds to the numeric value of 0.
+// Decimal is designed to be safe for concurrent use by multiple goroutines.
+type Decimal struct {
+	neg   bool // indicates whether the decimal is negative
+	scale int8 // position of the floating decimal point
+	coef  fint // numeric value without decimal point
+}
+
+const (
+	MaxPrec  = 19      // MaxPrec is the maximum length of the coefficient in decimal digits.
+	MinScale = 0       // MinScale is the minimum number of digits after the decimal point.
+	MaxScale = 19      // MaxScale is the maximum number of digits after the decimal point.
+	maxCoef  = maxFint // maxCoef is the maximum absolute value of the coefficient, which is equal to (10^MaxPrec - 1).
+)
+
+var (
+	NegOne              = MustNew(-1, 0)                         // NegOne represents the decimal value of -1.
+	Zero                = MustNew(0, 0)                          // Zero represents the decimal value of 0. For comparison purposes, use the IsZero method.
+	One                 = MustNew(1, 0)                          // One represents the decimal value of 1.
+	Two                 = MustNew(2, 0)                          // Two represents the decimal value of 2.
+	Ten                 = MustNew(10, 0)                         // Ten represents the decimal value of 10.
+	Hundred             = MustNew(100, 0)                        // Hundred represents the decimal value of 100.
+	Thousand            = MustNew(1_000, 0)                      // Thousand represents the decimal value of 1,000.
+	E                   = MustNew(2_718_281_828_459_045_235, 18) // E represents Euler’s number rounded to 18 digits.
+	Pi                  = MustNew(3_141_592_653_589_793_238, 18) // Pi represents the value of π rounded to 18 digits.
+	errDecimalOverflow  = errors.New("decimal overflow")
+	errInvalidDecimal   = errors.New("invalid decimal")
+	errScaleRange       = errors.New("scale out of range")
+	errInvalidOperation = errors.New("invalid operation")
+	errInexactDivision  = errors.New("inexact division")
+	errDivisionByZero   = errors.New("division by zero")
+)
+
+// newUnsafe creates a new decimal without checking the scale and coefficient.
+// Use it only if you are absolutely sure that the arguments are valid.
+func newUnsafe(neg bool, coef fint, scale int) Decimal {
+	if coef == 0 {
+		neg = false
+	}
+	//nolint:gosec
+	return Decimal{neg: neg, coef: coef, scale: int8(scale)}
+}
+
+// newSafe creates a new decimal and checks the scale and coefficient.
+func newSafe(neg bool, coef fint, scale int) (Decimal, error) {
+	switch {
+	case scale < MinScale || scale > MaxScale:
+		return Decimal{}, errScaleRange
+	case coef > maxCoef:
+		return Decimal{}, errDecimalOverflow
+	}
+	return newUnsafe(neg, coef, scale), nil
+}
+
+// newFromFint creates a new decimal from a uint64 coefficient.
+// This method does not use overflowError to return descriptive errors,
+// as it must be as fast as possible.
+func newFromFint(neg bool, coef fint, scale, minScale int) (Decimal, error) {
+	var ok bool
+	// Scale normalization
+	switch {
+	case scale < minScale:
+		coef, ok = coef.lsh(minScale - scale)
+		if !ok {
+			return Decimal{}, errDecimalOverflow
+		}
+		scale = minScale
+	case scale > MaxScale:
+		coef = coef.rshHalfEven(scale - MaxScale)
+		scale = MaxScale
+	}
+	return newSafe(neg, coef, scale)
+}
+
+// newFromBint creates a new decimal from a *big.Int coefficient.
+// This method uses overflowError to return descriptive errors.
+func newFromBint(neg bool, coef *bint, scale, minScale int) (Decimal, error) {
+	// Overflow validation
+	prec := coef.prec()
+	if prec-scale > MaxPrec-minScale {
+		return Decimal{}, overflowError(prec, scale, minScale)
+	}
+	// Scale normalization
+	switch {
+	case scale < minScale:
+		coef.lsh(coef, minScale-scale)
+		scale = minScale
+	case scale >= prec && scale > MaxScale: // no integer part
+		coef.rshHalfEven(coef, scale-MaxScale)
+		scale = MaxScale
+	case prec > scale && prec > MaxPrec: // there is an integer part
+		coef.rshHalfEven(coef, prec-MaxPrec)
+		scale = MaxPrec - prec + scale
+	}
+	// Handling the rare case when rshHalfEven rounded
+	// a 19-digit coefficient to a 20-digit coefficient.
+	if coef.hasPrec(MaxPrec + 1) {
+		return newFromBint(neg, coef, scale, minScale)
+	}
+	return newSafe(neg, coef.fint(), scale)
+}
+
+func overflowError(gotPrec, gotScale, wantScale int) error {
+	maxDigits := MaxPrec - wantScale
+	gotDigits := gotPrec - gotScale
+	switch wantScale {
+	case 0:
+		return fmt.Errorf("%w: the integer part of a %T can have at most %v digits, but it has %v digits", errDecimalOverflow, Decimal{}, maxDigits, gotDigits)
+	default:
+		return fmt.Errorf("%w: with %v significant digits after the decimal point, the integer part of a %T can have at most %v digits, but it has %v digits", errDecimalOverflow, wantScale, Decimal{}, maxDigits, gotDigits)
+	}
+}
+
+func unknownOverflowError() error {
+	return fmt.Errorf("%w: the integer part of a %T can have at most %v digits, but it has significantly more digits", errDecimalOverflow, Decimal{}, MaxPrec)
+}
+
+// MustNew is like [New] but panics if the decimal cannot be constructed.
+// It simplifies safe initialization of global variables holding decimals.
+func MustNew(value int64, scale int) Decimal {
+	d, err := New(value, scale)
+	if err != nil {
+		panic(fmt.Sprintf("New(%v, %v) failed: %v", value, scale, err))
+	}
+	return d
+}
+
+// New returns a decimal equal to value / 10^scale.
+// New keeps trailing zeros in the fractional part to preserve scale.
+//
+// New returns an error if the scale is negative or greater than [MaxScale].
+func New(value int64, scale int) (Decimal, error) {
+	var coef fint
+	var neg bool
+	if value >= 0 {
+		neg = false
+		coef = fint(value)
+	} else {
+		neg = true
+		if value == math.MinInt64 {
+			coef = fint(math.MaxInt64) + 1
+		} else {
+			coef = fint(-value)
+		}
+	}
+	return newSafe(neg, coef, scale)
+}
+
+// NewFromInt64 converts a pair of integers, representing the whole and
+// fractional parts, to a (possibly rounded) decimal equal to whole + frac / 10^scale.
+// NewFromInt64 removes all trailing zeros from the fractional part.
+// This method is useful for converting amounts from [protobuf] format.
+// See also method [Decimal.Int64].
+//
+// NewFromInt64 returns an error if:
+//   - the whole and fractional parts have different signs;
+//   - the scale is negative or greater than [MaxScale];
+//   - frac / 10^scale is not within the range (-1, 1).
+//
+// [protobuf]: https://github.com/googleapis/googleapis/blob/master/google/type/money.proto
+func NewFromInt64(whole, frac int64, scale int) (Decimal, error) {
+	// Whole
+	d, err := New(whole, 0)
+	if err != nil {
+		return Decimal{}, fmt.Errorf("converting integers: %w", err) // should never happen
+	}
+	// Fraction
+	f, err := New(frac, scale)
+	if err != nil {
+		return Decimal{}, fmt.Errorf("converting integers: %w", err)
+	}
+	if !f.IsZero() {
+		if !d.IsZero() && d.Sign() != f.Sign() {
+			return Decimal{}, fmt.Errorf("converting integers: inconsistent signs")
+		}
+		if !f.WithinOne() {
+			return Decimal{}, fmt.Errorf("converting integers: inconsistent fraction")
+		}
+		f = f.Trim(0)
+		d, err = d.Add(f)
+		if err != nil {
+			return Decimal{}, fmt.Errorf("converting integers: %w", err) // should never happen
+		}
+	}
+	return d, nil
+}
+
+// Int64 returns a pair of integers representing the whole and
+// (possibly rounded) fractional parts of the decimal.
+// If given scale is greater than the scale of the decimal, then the fractional part
+// is zero-padded to the right.
+// If given scale is smaller than the scale of the decimal, then the fractional part
+// is rounded using [rounding half to even] (banker's rounding).
+// The relationship between the decimal and the returned values can be expressed
+// as d = whole + frac / 10^scale.
+// This method is useful for converting amounts to [protobuf] format.
+// See also constructor [NewFromInt64].
+//
+// If the result cannot be represented as a pair of int64 values,
+// then false is returned.
+//
+// [rounding half to even]: https://en.wikipedia.org/wiki/Rounding#Rounding_half_to_even
+// [protobuf]: https://github.com/googleapis/googleapis/blob/master/google/type/money.proto
+func (d Decimal) Int64(scale int) (whole, frac int64, ok bool) {
+	if scale < MinScale || scale > MaxScale {
+		return 0, 0, false
+	}
+	x := d.coef
+	y := pow10[d.Scale()]
+	if scale < d.Scale() {
+		x = x.rshHalfEven(d.Scale() - scale)
+		y = pow10[scale]
+	}
+	q, r, ok := x.quoRem(y)
+	if !ok {
+		return 0, 0, false // Should never happen
+	}
+	if scale > d.Scale() {
+		r, ok = r.lsh(scale - d.Scale())
+		if !ok {
+			return 0, 0, false // Should never happen
+		}
+	}
+	if d.IsNeg() {
+		if q > -math.MinInt64 || r > -math.MinInt64 {
+			return 0, 0, false
+		}
+		//nolint:gosec
+		return -int64(q), -int64(r), true
+	}
+	if q > math.MaxInt64 || r > math.MaxInt64 {
+		return 0, 0, false
+	}
+	//nolint:gosec
+	return int64(q), int64(r), true
+}
+
+// NewFromFloat64 converts a float to a (possibly rounded) decimal.
+// See also method [Decimal.Float64].
+//
+// NewFromFloat64 returns an error if:
+//   - the float is a special value (NaN or Inf);
+//   - the integer part of the result has more than [MaxPrec] digits.
+func NewFromFloat64(f float64) (Decimal, error) {
+	// Float
+	if math.IsNaN(f) || math.IsInf(f, 0) {
+		return Decimal{}, fmt.Errorf("converting float: special value %v", f)
+	}
+	text := make([]byte, 0, 32)
+	text = strconv.AppendFloat(text, f, 'f', -1, 64)
+
+	// Decimal
+	d, err := parse(text)
+	if err != nil {
+		return Decimal{}, fmt.Errorf("converting float: %w", err)
+	}
+	return d, nil
+}
+
+// Float64 returns the nearest binary floating-point number rounded
+// using [rounding half to even] (banker's rounding).
+// See also constructor [NewFromFloat64].
+//
+// This conversion may lose data, as float64 has a smaller precision
+// than the decimal type.
+//
+// [rounding half to even]: https://en.wikipedia.org/wiki/Rounding#Rounding_half_to_even
+func (d Decimal) Float64() (f float64, ok bool) {
+	s := d.String()
+	f, err := strconv.ParseFloat(s, 64)
+	if err != nil {
+		return 0, false
+	}
+	return f, true
+}
+
+// MustParse is like [Parse] but panics if the string cannot be parsed.
+// It simplifies safe initialization of global variables holding decimals.
+func MustParse(s string) Decimal {
+	d, err := Parse(s)
+	if err != nil {
+		panic(fmt.Sprintf("Parse(%q) failed: %v", s, err))
+	}
+	return d
+}
+
+// Parse converts a string to a (possibly rounded) decimal.
+// The input string must be in one of the following formats:
+//
+//	1.234
+//	-1234
+//	+0.000001234
+//	1.83e5
+//	0.22e-9
+//
+// The formal EBNF grammar for the supported format is as follows:
+//
+//	sign           ::= '+' | '-'
+//	digits         ::= { '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' }
+//	significand    ::= digits '.' digits | '.' digits | digits '.' | digits
+//	exponent       ::= ('e' | 'E') [sign] digits
+//	numeric-string ::= [sign] significand [exponent]
+//
+// Parse removes leading zeros from the integer part of the input string,
+// but tries to maintain trailing zeros in the fractional part to preserve scale.
+//
+// Parse returns an error if:
+//   - the string contains any whitespaces;
+//   - the string is longer than 330 bytes;
+//   - the exponent is less than -330 or greater than 330;
+//   - the string does not represent a valid decimal number;
+//   - the integer part of the result has more than [MaxPrec] digits.
+func Parse(s string) (Decimal, error) {
+	text := unsafe.Slice(unsafe.StringData(s), len(s))
+	return parseExact(text, 0)
+}
+
+func parse(text []byte) (Decimal, error) {
+	return parseExact(text, 0)
+}
+
+// ParseExact is similar to [Parse], but it allows you to specify how many digits
+// after the decimal point should be considered significant.
+// If any of the significant digits are lost during rounding, the method will return an error.
+// This method is useful for parsing monetary amounts, where the scale should be
+// equal to or greater than the currency's scale.
+func ParseExact(s string, scale int) (Decimal, error) {
+	text := unsafe.Slice(unsafe.StringData(s), len(s))
+	return parseExact(text, scale)
+}
+
+func parseExact(text []byte, scale int) (Decimal, error) {
+	if len(text) > 330 {
+		return Decimal{}, fmt.Errorf("parsing decimal: %w", errInvalidDecimal)
+	}
+	if scale < MinScale || scale > MaxScale {
+		return Decimal{}, fmt.Errorf("parsing decimal: %w", errScaleRange)
+	}
+	d, err := parseFint(text, scale)
+	if err != nil {
+		d, err = parseBint(text, scale)
+		if err != nil {
+			return Decimal{}, fmt.Errorf("parsing decimal: %w", err)
+		}
+	}
+	return d, nil
+}
+
+// parseFint parses a decimal string using uint64 arithmetic.
+// parseFint does not support exponential notation to make it as fast as possible.
+//
+//nolint:gocyclo
+func parseFint(text []byte, minScale int) (Decimal, error) {
+	var pos int
+	width := len(text)
+
+	// Sign
+	var neg bool
+	switch {
+	case pos == width:
+		// skip
+	case text[pos] == '-':
+		neg = true
+		pos++
+	case text[pos] == '+':
+		pos++
+	}
+
+	// Coefficient
+	var coef fint
+	var scale int
+	var hasCoef, ok bool
+
+	// Integer
+	for pos < width && text[pos] >= '0' && text[pos] <= '9' {
+		coef, ok = coef.fsa(1, text[pos]-'0')
+		if !ok {
+			return Decimal{}, errDecimalOverflow
+		}
+		pos++
+		hasCoef = true
+	}
+
+	// Fraction
+	if pos < width && text[pos] == '.' {
+		pos++
+		for pos < width && text[pos] >= '0' && text[pos] <= '9' {
+			coef, ok = coef.fsa(1, text[pos]-'0')
+			if !ok {
+				return Decimal{}, errDecimalOverflow
+			}
+			pos++
+			scale++
+			hasCoef = true
+		}
+	}
+
+	if pos != width {
+		return Decimal{}, fmt.Errorf("%w: unexpected character %q", errInvalidDecimal, text[pos])
+	}
+	if !hasCoef {
+		return Decimal{}, fmt.Errorf("%w: no coefficient", errInvalidDecimal)
+	}
+	return newFromFint(neg, coef, scale, minScale)
+}
+
+// parseBint parses a decimal string using *big.Int arithmetic.
+// parseBint supports exponential notation.
+//
+//nolint:gocyclo
+func parseBint(text []byte, minScale int) (Decimal, error) {
+	var pos int
+	width := len(text)
+
+	// Sign
+	var neg bool
+	switch {
+	case pos == width:
+		// skip
+	case text[pos] == '-':
+		neg = true
+		pos++
+	case text[pos] == '+':
+		pos++
+	}
+
+	// Coefficient
+	bcoef := getBint()
+	defer putBint(bcoef)
+	var fcoef fint
+	var shift, scale int
+	var hasCoef, ok bool
+
+	bcoef.setFint(0)
+
+	// Algorithm:
+	// 	1. Add as many digits as possible to the uint64 coefficient (fast).
+	// 	2. Once the uint64 coefficient has reached its maximum value,
+	//     add it to the *big.Int coefficient (slow).
+	// 	3. Repeat until all digits are processed.
+
+	// Integer
+	for pos < width && text[pos] >= '0' && text[pos] <= '9' {
+		fcoef, ok = fcoef.fsa(1, text[pos]-'0')
+		if !ok {
+			return Decimal{}, errDecimalOverflow // Should never happen
+		}
+		pos++
+		shift++
+		hasCoef = true
+		if fcoef.hasPrec(MaxPrec) {
+			bcoef.fsa(bcoef, shift, fcoef)
+			fcoef, shift = 0, 0
+		}
+	}
+
+	// Fraction
+	if pos < width && text[pos] == '.' {
+		pos++
+		for pos < width && text[pos] >= '0' && text[pos] <= '9' {
+			fcoef, ok = fcoef.fsa(1, text[pos]-'0')
+			if !ok {
+				return Decimal{}, errDecimalOverflow // Should never happen
+			}
+			pos++
+			scale++
+			shift++
+			hasCoef = true
+			if fcoef.hasPrec(MaxPrec) {
+				bcoef.fsa(bcoef, shift, fcoef)
+				fcoef, shift = 0, 0
+			}
+		}
+	}
+	if shift > 0 {
+		bcoef.fsa(bcoef, shift, fcoef)
+	}
+
+	// Exponent
+	var exp int
+	var eneg, hasExp, hasE bool
+	if pos < width && (text[pos] == 'e' || text[pos] == 'E') {
+		pos++
+		hasE = true
+		// Sign
+		switch {
+		case pos == width:
+			// skip
+		case text[pos] == '-':
+			eneg = true
+			pos++
+		case text[pos] == '+':
+			pos++
+		}
+		// Integer
+		for pos < width && text[pos] >= '0' && text[pos] <= '9' {
+			exp = exp*10 + int(text[pos]-'0')
+			if exp > 330 {
+				return Decimal{}, errInvalidDecimal
+			}
+			pos++
+			hasExp = true
+		}
+	}
+
+	if pos != width {
+		return Decimal{}, fmt.Errorf("%w: unexpected character %q", errInvalidDecimal, text[pos])
+	}
+	if !hasCoef {
+		return Decimal{}, fmt.Errorf("%w: no coefficient", errInvalidDecimal)
+	}
+	if hasE && !hasExp {
+		return Decimal{}, fmt.Errorf("%w: no exponent", errInvalidDecimal)
+	}
+
+	if eneg {
+		scale = scale + exp
+	} else {
+		scale = scale - exp
+	}
+
+	return newFromBint(neg, bcoef, scale, minScale)
+}
+
+// String implements the [fmt.Stringer] interface and returns
+// a string representation of the decimal.
+// The returned string does not use scientific or engineering notation and is
+// formatted according to the following formal EBNF grammar:
+//
+//	sign           ::= '-'
+//	digits         ::= { '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' }
+//	significand    ::= digits '.' digits | digits
+//	numeric-string ::= [sign] significand
+//
+// See also method [Decimal.Format].
+//
+// [fmt.Stringer]: https://pkg.go.dev/fmt#Stringer
+func (d Decimal) String() string {
+	return string(d.bytes())
+}
+
+// bytes returns a string representation of the decimal as a byte slice.
+func (d Decimal) bytes() []byte {
+	text := make([]byte, 0, 24)
+	return d.append(text)
+}
+
+// append appends a string representation of the decimal to the byte slice.
+func (d Decimal) append(text []byte) []byte {
+	var buf [24]byte
+	pos := len(buf) - 1
+	coef := d.Coef()
+	scale := d.Scale()
+
+	// Coefficient
+	for {
+		buf[pos] = byte(coef%10) + '0'
+		pos--
+		coef /= 10
+		if scale > 0 {
+			scale--
+			// Decimal point
+			if scale == 0 {
+				buf[pos] = '.'
+				pos--
+				// Leading 0
+				if coef == 0 {
+					buf[pos] = '0'
+					pos--
+				}
+			}
+		}
+		if coef == 0 && scale == 0 {
+			break
+		}
+	}
+
+	// Sign
+	if d.IsNeg() {
+		buf[pos] = '-'
+		pos--
+	}
+
+	return append(text, buf[pos+1:]...)
+}
+
+// UnmarshalJSON implements the [json.Unmarshaler] interface.
+// UnmarshalJSON supports the following types: [number] and [numeric string].
+// See also constructor [Parse].
+//
+// [number]: https://datatracker.ietf.org/doc/html/rfc8259#section-6
+// [numeric string]: https://datatracker.ietf.org/doc/html/rfc8259#section-7
+// [json.Unmarshaler]: https://pkg.go.dev/encoding/json#Unmarshaler
+func (d *Decimal) UnmarshalJSON(data []byte) error {
+	if string(data) == "null" {
+		return nil
+	}
+	if len(data) >= 2 && data[0] == '"' && data[len(data)-1] == '"' {
+		data = data[1 : len(data)-1]
+	}
+	var err error
+	*d, err = parse(data)
+	if err != nil {
+		return fmt.Errorf("unmarshaling %T: %w", Decimal{}, err)
+	}
+	return nil
+}
+
+// MarshalJSON implements the [json.Marshaler] interface.
+// MarshalJSON always returns a [numeric string].
+// See also method [Decimal.String].
+//
+// [numeric string]: https://datatracker.ietf.org/doc/html/rfc8259#section-7
+// [json.Marshaler]: https://pkg.go.dev/encoding/json#Marshaler
+func (d Decimal) MarshalJSON() ([]byte, error) {
+	text := make([]byte, 0, 26)
+	text = append(text, '"')
+	text = d.append(text)
+	text = append(text, '"')
+	return text, nil
+}
+
+// UnmarshalText implements the [encoding.TextUnmarshaler] interface.
+// UnmarshalText supports only numeric strings.
+// See also constructor [Parse].
+//
+// [encoding.TextUnmarshaler]: https://pkg.go.dev/encoding#TextUnmarshaler
+func (d *Decimal) UnmarshalText(text []byte) error {
+	var err error
+	*d, err = parse(text)
+	if err != nil {
+		return fmt.Errorf("unmarshaling %T: %w", Decimal{}, err)
+	}
+	return nil
+}
+
+// AppendText implements the [encoding.TextAppender] interface.
+// AppendText always appends a numeric string.
+// See also method [Decimal.String].
+//
+// [encoding.TextAppender]: https://pkg.go.dev/encoding#TextAppender
+func (d Decimal) AppendText(text []byte) ([]byte, error) {
+	return d.append(text), nil
+}
+
+// MarshalText implements the [encoding.TextMarshaler] interface.
+// MarshalText always returns a numeric string.
+// See also method [Decimal.String].
+//
+// [encoding.TextMarshaler]: https://pkg.go.dev/encoding#TextMarshaler
+func (d Decimal) MarshalText() ([]byte, error) {
+	return d.bytes(), nil
+}
+
+// UnmarshalBinary implements the [encoding.BinaryUnmarshaler] interface.
+// UnmarshalBinary supports only numeric strings.
+// See also constructor [Parse].
+//
+// [encoding.BinaryUnmarshaler]: https://pkg.go.dev/encoding#BinaryUnmarshaler
+func (d *Decimal) UnmarshalBinary(data []byte) error {
+	var err error
+	*d, err = parse(data)
+	if err != nil {
+		return fmt.Errorf("unmarshaling %T: %w", Decimal{}, err)
+	}
+	return nil
+}
+
+// AppendBinary implements the [encoding.BinaryAppender] interface.
+// AppendBinary always appends a numeric string.
+// See also method [Decimal.String].
+//
+// [encoding.BinaryAppender]: https://pkg.go.dev/encoding#BinaryAppender
+func (d Decimal) AppendBinary(data []byte) ([]byte, error) {
+	return d.append(data), nil
+}
+
+// MarshalBinary implements the [encoding.BinaryMarshaler] interface.
+// MarshalBinary always returns a numeric string.
+// See also method [Decimal.String].
+//
+// [encoding.BinaryMarshaler]: https://pkg.go.dev/encoding#BinaryMarshaler
+func (d Decimal) MarshalBinary() ([]byte, error) {
+	return d.bytes(), nil
+}
+
+// UnmarshalBSONValue implements the [v2/bson.ValueUnmarshaler] interface.
+// UnmarshalBSONValue supports the following [types]: Double, String, 32-bit Integer, 64-bit Integer, and [Decimal128].
+//
+// [v2/bson.ValueUnmarshaler]: https://pkg.go.dev/go.mongodb.org/mongo-driver/v2/bson#ValueUnmarshaler
+// [types]: https://bsonspec.org/spec.html
+// [Decimal128]: https://github.com/mongodb/specifications/blob/master/source/bson-decimal128/decimal128.md
+func (d *Decimal) UnmarshalBSONValue(typ byte, data []byte) error {
+	// constants are from https://bsonspec.org/spec.html
+	var err error
+	switch typ {
+	case 1:
+		*d, err = parseBSONFloat64(data)
+	case 2:
+		*d, err = parseBSONString(data)
+	case 10:
+		// null, do nothing
+	case 16:
+		*d, err = parseBSONInt32(data)
+	case 18:
+		*d, err = parseBSONInt64(data)
+	case 19:
+		*d, err = parseIEEEDecimal128(data)
+	default:
+		err = fmt.Errorf("BSON type %d is not supported", typ)
+	}
+	if err != nil {
+		err = fmt.Errorf("converting from BSON type %d to %T: %w", typ, Decimal{}, err)
+	}
+	return err
+}
+
+// MarshalBSONValue implements the [v2/bson.ValueMarshaler] interface.
+// MarshalBSONValue always returns [Decimal128].
+//
+// [v2/bson.ValueMarshaler]: https://pkg.go.dev/go.mongodb.org/mongo-driver/v2/bson#ValueMarshaler
+// [Decimal128]: https://github.com/mongodb/specifications/blob/master/source/bson-decimal128/decimal128.md
+func (d Decimal) MarshalBSONValue() (typ byte, data []byte, err error) {
+	return 19, d.ieeeDecimal128(), nil
+}
+
+// parseBSONInt32 parses a BSON int32 to a decimal.
+// The byte order of the input data must be little-endian.
+func parseBSONInt32(data []byte) (Decimal, error) {
+	if len(data) != 4 {
+		return Decimal{}, fmt.Errorf("%w: invalid data length %v", errInvalidDecimal, len(data))
+	}
+	u := uint32(data[0])
+	u |= uint32(data[1]) << 8
+	u |= uint32(data[2]) << 16
+	u |= uint32(data[3]) << 24
+	i := int64(int32(u)) //nolint:gosec
+	return New(i, 0)
+}
+
+// parseBSONInt64 parses a BSON int64 to a decimal.
+// The byte order of the input data must be little-endian.
+func parseBSONInt64(data []byte) (Decimal, error) {
+	if len(data) != 8 {
+		return Decimal{}, fmt.Errorf("%w: invalid data length %v", errInvalidDecimal, len(data))
+	}
+	u := uint64(data[0])
+	u |= uint64(data[1]) << 8
+	u |= uint64(data[2]) << 16
+	u |= uint64(data[3]) << 24
+	u |= uint64(data[4]) << 32
+	u |= uint64(data[5]) << 40
+	u |= uint64(data[6]) << 48
+	u |= uint64(data[7]) << 56
+	i := int64(u) //nolint:gosec
+	return New(i, 0)
+}
+
+// parseBSONFloat64 parses a BSON float64 to a (possibly rounded) decimal.
+// The byte order of the input data must be little-endian.
+func parseBSONFloat64(data []byte) (Decimal, error) {
+	if len(data) != 8 {
+		return Decimal{}, fmt.Errorf("%w: invalid data length %v", errInvalidDecimal, len(data))
+	}
+	u := uint64(data[0])
+	u |= uint64(data[1]) << 8
+	u |= uint64(data[2]) << 16
+	u |= uint64(data[3]) << 24
+	u |= uint64(data[4]) << 32
+	u |= uint64(data[5]) << 40
+	u |= uint64(data[6]) << 48
+	u |= uint64(data[7]) << 56
+	f := math.Float64frombits(u)
+	return NewFromFloat64(f)
+}
+
+// parseBSONString parses a BSON string to a (possibly rounded) decimal.
+// The byte order of the input data must be little-endian.
+func parseBSONString(data []byte) (Decimal, error) {
+	if len(data) < 4 {
+		return Decimal{}, fmt.Errorf("%w: invalid data length %v", errInvalidDecimal, len(data))
+	}
+	u := uint32(data[0])
+	u |= uint32(data[1]) << 8
+	u |= uint32(data[2]) << 16
+	u |= uint32(data[3]) << 24
+	l := int(int32(u)) //nolint:gosec
+	if l < 1 || l > 330 || len(data) < l+4 {
+		return Decimal{}, fmt.Errorf("%w: invalid string length %v", errInvalidDecimal, l)
+	}
+	if data[l+4-1] != 0 {
+		return Decimal{}, fmt.Errorf("%w: invalid null terminator %v", errInvalidDecimal, data[l+4-1])
+	}
+	s := string(data[4 : l+4-1])
+	return Parse(s)
+}
+
+// parseIEEEDecimal128 converts a 128-bit IEEE 754-2008 decimal
+// floating point with binary integer decimal encoding to
+// a (possibly rounded) decimal.
+// The byte order of the input data must be little-endian.
+//
+// parseIEEEDecimal128 returns an error if:
+//   - the data length is not equal to 16 bytes;
+//   - the decimal a special value (NaN or Inf);
+//   - the integer part of the result has more than [MaxPrec] digits.
+func parseIEEEDecimal128(data []byte) (Decimal, error) {
+	if len(data) != 16 {
+		return Decimal{}, fmt.Errorf("%w: invalid data length %v", errInvalidDecimal, len(data))
+	}
+	if data[15]&0b0111_1100 == 0b0111_1100 {
+		return Decimal{}, fmt.Errorf("%w: special value NaN", errInvalidDecimal)
+	}
+	if data[15]&0b0111_1100 == 0b0111_1000 {
+		return Decimal{}, fmt.Errorf("%w: special value Inf", errInvalidDecimal)
+	}
+	if data[15]&0b0110_0000 == 0b0110_0000 {
+		return Decimal{}, fmt.Errorf("%w: unsupported encoding", errInvalidDecimal)
+	}
+
+	// Sign
+	neg := data[15]&0b1000_0000 == 0b1000_0000
+
+	// Scale
+	var scale int
+	scale |= int(data[14]) >> 1
+	scale |= int(data[15]&0b0111_1111) << 7
+	scale = 6176 - scale
+
+	// TODO fint optimization
+
+	// Coefficient
+	coef := getBint()
+	defer putBint(coef)
+
+	buf := make([]byte, 15)
+	for i := range 15 {
+		buf[i] = data[14-i]
+	}
+	buf[0] &= 0b0000_0001
+	coef.setBytes(buf)
+
+	// Scale normalization
+	if coef.sign() == 0 {
+		scale = max(scale, MinScale)
+	}
+
+	return newFromBint(neg, coef, scale, 0)
+}
+
+// ieeeDecimal128 returns a 128-bit IEEE 754-2008 decimal
+// floating point with binary integer decimal encoding.
+// The byte order of the result is little-endian.
+func (d Decimal) ieeeDecimal128() []byte {
+	var buf [16]byte
+	scale := d.Scale()
+	coef := d.Coef()
+
+	// Sign
+	if d.IsNeg() {
+		buf[15] = 0b1000_0000
+	}
+
+	// Scale
+	scale = 6176 - scale
+	buf[15] |= byte((scale >> 7) & 0b0111_1111)
+	buf[14] |= byte((scale << 1) & 0b1111_1110)
+
+	// Coefficient
+	for i := range 8 {
+		buf[i] = byte(coef & 0b1111_1111)
+		coef >>= 8
+	}
+
+	return buf[:]
+}
+
+// Scan implements the [sql.Scanner] interface.
+//
+// [sql.Scanner]: https://pkg.go.dev/database/sql#Scanner
+func (d *Decimal) Scan(value any) error {
+	var err error
+	switch value := value.(type) {
+	case string:
+		*d, err = Parse(value)
+	case int64:
+		*d, err = New(value, 0)
+	case float64:
+		*d, err = NewFromFloat64(value)
+	case []byte:
+		// Special case: MySQL driver sends DECIMAL as []byte
+		*d, err = parse(value)
+	case float32:
+		// Special case: MySQL driver sends FLOAT as float32
+		*d, err = NewFromFloat64(float64(value))
+	case uint64:
+		// Special case: ClickHouse driver sends 0 as uint64
+		*d, err = newSafe(false, fint(value), 0)
+	case nil:
+		err = fmt.Errorf("%T does not support null values, use %T or *%T", Decimal{}, NullDecimal{}, Decimal{})
+	default:
+		err = fmt.Errorf("type %T is not supported", value)
+	}
+	if err != nil {
+		err = fmt.Errorf("converting from %T to %T: %w", value, Decimal{}, err)
+	}
+	return err
+}
+
+// Value implements the [driver.Valuer] interface.
+//
+// [driver.Valuer]: https://pkg.go.dev/database/sql/driver#Valuer
+func (d Decimal) Value() (driver.Value, error) {
+	return d.String(), nil
+}
+
+// Format implements the [fmt.Formatter] interface.
+// The following [format verbs] are available:
+//
+//	| Verb       | Example | Description    |
+//	| ---------- | ------- | -------------- |
+//	| %f, %s, %v | 5.67    | Decimal        |
+//	| %q         | "5.67"  | Quoted decimal |
+//	| %k         | 567%    | Percentage     |
+//
+// The following format flags can be used with all verbs: '+', ' ', '0', '-'.
+//
+// Precision is only supported for %f and %k verbs.
+// For %f verb, the default precision is equal to the actual scale of the decimal,
+// whereas, for verb %k the default precision is the actual scale of the decimal minus 2.
+//
+// [format verbs]: https://pkg.go.dev/fmt#hdr-Printing
+// [fmt.Formatter]: https://pkg.go.dev/fmt#Formatter
+//
+//nolint:gocyclo
+func (d Decimal) Format(state fmt.State, verb rune) {
+	var err error
+
+	// Percentage multiplier
+	if verb == 'k' || verb == 'K' {
+		d, err = d.Mul(Hundred)
+		if err != nil {
+			// This panic is handled inside the fmt package.
+			panic(fmt.Errorf("formatting percent: %w", err))
+		}
+	}
+
+	// Rescaling
+	var tzeros int
+	if verb == 'f' || verb == 'F' || verb == 'k' || verb == 'K' {
+		var scale int
+		switch p, ok := state.Precision(); {
+		case ok:
+			scale = p
+		case verb == 'k' || verb == 'K':
+			scale = d.Scale() - 2
+		case verb == 'f' || verb == 'F':
+			scale = d.Scale()
+		}
+		scale = max(scale, MinScale)
+		switch {
+		case scale < d.Scale():
+			d = d.Round(scale)
+		case scale > d.Scale():
+			tzeros = scale - d.Scale()
+		}
+	}
+
+	// Integer and fractional digits
+	var intdigs int
+	fracdigs := d.Scale()
+	if dprec := d.Prec(); dprec > fracdigs {
+		intdigs = dprec - fracdigs
+	}
+	if d.WithinOne() {
+		intdigs++ // leading 0
+	}
+
+	// Decimal point
+	var dpoint int
+	if fracdigs > 0 || tzeros > 0 {
+		dpoint = 1
+	}
+
+	// Arithmetic sign
+	var rsign int
+	if d.IsNeg() || state.Flag('+') || state.Flag(' ') {
+		rsign = 1
+	}
+
+	// Percentage sign
+	var psign int
+	if verb == 'k' || verb == 'K' {
+		psign = 1
+	}
+
+	// Openning and closing quotes
+	var lquote, tquote int
+	if verb == 'q' || verb == 'Q' {
+		lquote, tquote = 1, 1
+	}
+
+	// Calculating padding
+	width := lquote + rsign + intdigs + dpoint + fracdigs + tzeros + psign + tquote
+	var lspaces, tspaces, lzeros int
+	if w, ok := state.Width(); ok && w > width {
+		switch {
+		case state.Flag('-'):
+			tspaces = w - width
+		case state.Flag('0'):
+			lzeros = w - width
+		default:
+			lspaces = w - width
+		}
+		width = w
+	}
+
+	buf := make([]byte, width)
+	pos := width - 1
+
+	// Trailing spaces
+	for range tspaces {
+		buf[pos] = ' '
+		pos--
+	}
+
+	// Closing quote
+	for range tquote {
+		buf[pos] = '"'
+		pos--
+	}
+
+	// Percentage sign
+	for range psign {
+		buf[pos] = '%'
+		pos--
+	}
+
+	// Trailing zeros
+	for range tzeros {
+		buf[pos] = '0'
+		pos--
+	}
+
+	// Fractional digits
+	dcoef := d.Coef()
+	for range fracdigs {
+		buf[pos] = byte(dcoef%10) + '0'
+		pos--
+		dcoef /= 10
+	}
+
+	// Decimal point
+	for range dpoint {
+		buf[pos] = '.'
+		pos--
+	}
+
+	// Integer digits
+	for range intdigs {
+		buf[pos] = byte(dcoef%10) + '0'
+		pos--
+		dcoef /= 10
+	}
+
+	// Leading zeros
+	for range lzeros {
+		buf[pos] = '0'
+		pos--
+	}
+
+	// Arithmetic sign
+	for range rsign {
+		if d.IsNeg() {
+			buf[pos] = '-'
+		} else if state.Flag(' ') {
+			buf[pos] = ' '
+		} else {
+			buf[pos] = '+'
+		}
+		pos--
+	}
+
+	// Opening quote
+	for range lquote {
+		buf[pos] = '"'
+		pos--
+	}
+
+	// Leading spaces
+	for range lspaces {
+		buf[pos] = ' '
+		pos--
+	}
+
+	// Writing result
+	//nolint:errcheck
+	switch verb {
+	case 'q', 'Q', 's', 'S', 'v', 'V', 'f', 'F', 'k', 'K':
+		state.Write(buf)
+	default:
+		state.Write([]byte("%!"))
+		state.Write([]byte{byte(verb)})
+		state.Write([]byte("(decimal.Decimal="))
+		state.Write(buf)
+		state.Write([]byte(")"))
+	}
+}
+
+// Zero returns a decimal with a value of 0, having the same scale as decimal d.
+// See also methods [Decimal.One], [Decimal.ULP].
+func (d Decimal) Zero() Decimal {
+	return newUnsafe(false, 0, d.Scale())
+}
+
+// One returns a decimal with a value of 1, having the same scale as decimal d.
+// See also methods [Decimal.Zero], [Decimal.ULP].
+func (d Decimal) One() Decimal {
+	return newUnsafe(false, pow10[d.Scale()], d.Scale())
+}
+
+// ULP (Unit in the Last Place) returns the smallest representable positive
+// difference between two decimals with the same scale as decimal d.
+// It can be useful for implementing rounding and comparison algorithms.
+// See also methods [Decimal.Zero], [Decimal.One].
+func (d Decimal) ULP() Decimal {
+	return newUnsafe(false, 1, d.Scale())
+}
+
+// Prec returns the number of digits in the coefficient.
+// See also method [Decimal.Coef].
+func (d Decimal) Prec() int {
+	return d.coef.prec()
+}
+
+// Coef returns the coefficient of the decimal.
+// See also method [Decimal.Prec].
+func (d Decimal) Coef() uint64 {
+	return uint64(d.coef)
+}
+
+// Scale returns the number of digits after the decimal point.
+// See also methods [Decimal.Prec], [Decimal.MinScale].
+func (d Decimal) Scale() int {
+	return int(d.scale)
+}
+
+// MinScale returns the smallest scale that the decimal can be rescaled to
+// without rounding.
+// See also method [Decimal.Trim].
+func (d Decimal) MinScale() int {
+	// Special case: zero
+	if d.IsZero() {
+		return MinScale
+	}
+	// General case
+	dcoef := d.coef
+	return max(MinScale, d.Scale()-dcoef.ntz())
+}
+
+// IsInt returns true if there are no significant digits after the decimal point.
+func (d Decimal) IsInt() bool {
+	return d.Scale() == 0 || d.coef%pow10[d.Scale()] == 0
+}
+
+// IsOne returns:
+//
+//	true  if d = -1 or d = 1
+//	false otherwise
+func (d Decimal) IsOne() bool {
+	return d.coef == pow10[d.Scale()]
+}
+
+// WithinOne returns:
+//
+//	true  if -1 < d < 1
+//	false otherwise
+func (d Decimal) WithinOne() bool {
+	return d.coef < pow10[d.Scale()]
+}
+
+// Round returns a decimal rounded to the specified number of digits after
+// the decimal point using [rounding half to even] (banker's rounding).
+// If the given scale is negative, it is redefined to zero.
+// For financial calculations, the scale should be equal to or greater than
+// the scale of the currency.
+// See also method [Decimal.Rescale].
+//
+// [rounding half to even]: https://en.wikipedia.org/wiki/Rounding#Rounding_half_to_even
+func (d Decimal) Round(scale int) Decimal {
+	scale = max(scale, MinScale)
+	if scale >= d.Scale() {
+		return d
+	}
+	coef := d.coef
+	coef = coef.rshHalfEven(d.Scale() - scale)
+	return newUnsafe(d.IsNeg(), coef, scale)
+}
+
+// Pad returns a decimal zero-padded to the specified number of digits after
+// the decimal point.
+// The total number of digits in the result is limited by [MaxPrec].
+// See also method [Decimal.Trim].
+func (d Decimal) Pad(scale int) Decimal {
+	scale = min(scale, MaxScale, MaxPrec-d.Prec()+d.Scale())
+	if scale <= d.Scale() {
+		return d
+	}
+	coef := d.coef
+	coef, ok := coef.lsh(scale - d.Scale())
+	if !ok {
+		return d // Should never happen
+	}
+	return newUnsafe(d.IsNeg(), coef, scale)
+}
+
+// Rescale returns a decimal rounded or zero-padded to the given number of digits
+// after the decimal point.
+// If the given scale is negative, it is redefined to zero.
+// For financial calculations, the scale should be equal to or greater than
+// the scale of the currency.
+// See also methods [Decimal.Round], [Decimal.Pad].
+func (d Decimal) Rescale(scale int) Decimal {
+	if scale > d.Scale() {
+		return d.Pad(scale)
+	}
+	return d.Round(scale)
+}
+
+// Quantize returns a decimal rescaled to the same scale as decimal e.
+// The sign and the coefficient of decimal e are ignored.
+// See also methods [Decimal.SameScale] and [Decimal.Rescale].
+func (d Decimal) Quantize(e Decimal) Decimal {
+	return d.Rescale(e.Scale())
+}
+
+// SameScale returns true if decimals have the same scale.
+// See also methods [Decimal.Scale], [Decimal.Quantize].
+func (d Decimal) SameScale(e Decimal) bool {
+	return d.Scale() == e.Scale()
+}
+
+// Trunc returns a decimal truncated to the specified number of digits
+// after the decimal point using [rounding toward zero].
+// If the given scale is negative, it is redefined to zero.
+// For financial calculations, the scale should be equal to or greater than
+// the scale of the currency.
+//
+// [rounding toward zero]: https://en.wikipedia.org/wiki/Rounding#Rounding_toward_zero
+func (d Decimal) Trunc(scale int) Decimal {
+	scale = max(scale, MinScale)
+	if scale >= d.Scale() {
+		return d
+	}
+	coef := d.coef
+	coef = coef.rshDown(d.Scale() - scale)
+	return newUnsafe(d.IsNeg(), coef, scale)
+}
+
+// Trim returns a decimal with trailing zeros removed up to the given number of
+// digits after the decimal point.
+// If the given scale is negative, it is redefined to zero.
+// See also method [Decimal.Pad].
+func (d Decimal) Trim(scale int) Decimal {
+	if d.Scale() <= scale {
+		return d
+	}
+	scale = max(scale, d.MinScale())
+	return d.Trunc(scale)
+}
+
+// Ceil returns a decimal rounded up to the given number of digits
+// after the decimal point using [rounding toward positive infinity].
+// If the given scale is negative, it is redefined to zero.
+// For financial calculations, the scale should be equal to or greater than
+// the scale of the currency.
+// See also method [Decimal.Floor].
+//
+// [rounding toward positive infinity]: https://en.wikipedia.org/wiki/Rounding#Rounding_up
+func (d Decimal) Ceil(scale int) Decimal {
+	scale = max(scale, MinScale)
+	if scale >= d.Scale() {
+		return d
+	}
+	coef := d.coef
+	if d.IsNeg() {
+		coef = coef.rshDown(d.Scale() - scale)
+	} else {
+		coef = coef.rshUp(d.Scale() - scale)
+	}
+	return newUnsafe(d.IsNeg(), coef, scale)
+}
+
+// Floor returns a decimal rounded down to the specified number of digits
+// after the decimal point using [rounding toward negative infinity].
+// If the given scale is negative, it is redefined to zero.
+// For financial calculations, the scale should be equal to or greater than
+// the scale of the currency.
+// See also method [Decimal.Ceil].
+//
+// [rounding toward negative infinity]: https://en.wikipedia.org/wiki/Rounding#Rounding_down
+func (d Decimal) Floor(scale int) Decimal {
+	scale = max(scale, MinScale)
+	if scale >= d.Scale() {
+		return d
+	}
+	coef := d.coef
+	if d.IsNeg() {
+		coef = coef.rshUp(d.Scale() - scale)
+	} else {
+		coef = coef.rshDown(d.Scale() - scale)
+	}
+	return newUnsafe(d.IsNeg(), coef, scale)
+}
+
+// Neg returns a decimal with the opposite sign.
+func (d Decimal) Neg() Decimal {
+	return newUnsafe(!d.IsNeg(), d.coef, d.Scale())
+}
+
+// Abs returns the absolute value of the decimal.
+func (d Decimal) Abs() Decimal {
+	return newUnsafe(false, d.coef, d.Scale())
+}
+
+// CopySign returns a decimal with the same sign as decimal e.
+// CopySign treates 0 as positive.
+// See also method [Decimal.Sign].
+func (d Decimal) CopySign(e Decimal) Decimal {
+	if d.IsNeg() == e.IsNeg() {
+		return d
+	}
+	return d.Neg()
+}
+
+// Sign returns:
+//
+//	-1 if d < 0
+//	 0 if d = 0
+//	+1 if d > 0
+//
+// See also methods [Decimal.IsPos], [Decimal.IsNeg], [Decimal.IsZero].
+func (d Decimal) Sign() int {
+	switch {
+	case d.neg:
+		return -1
+	case d.coef == 0:
+		return 0
+	}
+	return 1
+}
+
+// IsPos returns:
+//
+//	true  if d > 0
+//	false otherwise
+func (d Decimal) IsPos() bool {
+	return d.coef != 0 && !d.neg
+}
+
+// IsNeg returns:
+//
+//	true  if d < 0
+//	false otherwise
+func (d Decimal) IsNeg() bool {
+	return d.neg
+}
+
+// IsZero returns:
+//
+//	true  if d = 0
+//	false otherwise
+func (d Decimal) IsZero() bool {
+	return d.coef == 0
+}
+
+// Prod returns the (possibly rounded) product of decimals.
+// It computes d1 * d2 * ... * dn with at least double precision
+// during the intermediate rounding.
+//
+// Prod returns an error if:
+//   - no arguments are provided;
+//   - the integer part of the result has more than [MaxPrec] digits.
+func Prod(d ...Decimal) (Decimal, error) {
+	// Special cases
+	switch len(d) {
+	case 0:
+		return Decimal{}, fmt.Errorf("computing [prod([])]: %w", errInvalidOperation)
+	case 1:
+		return d[0], nil
+	}
+
+	// General case
+	e, err := prodFint(d...)
+	if err != nil {
+		e, err = prodBint(d...)
+		if err != nil {
+			return Decimal{}, fmt.Errorf("computing [prod(%v)]: %w", d, err)
+		}
+	}
+
+	return e, nil
+}
+
+// prodFint computes the product of decimals using uint64 arithmetic.
+func prodFint(d ...Decimal) (Decimal, error) {
+	ecoef := One.coef
+	escale := One.Scale()
+	eneg := One.IsNeg()
+
+	for _, f := range d {
+		fcoef := f.coef
+
+		// Compute e = e * f
+		var ok bool
+		ecoef, ok = ecoef.mul(fcoef)
+		if !ok {
+			return Decimal{}, errDecimalOverflow
+		}
+		eneg = eneg != f.IsNeg()
+		escale = escale + f.Scale()
+	}
+
+	return newFromFint(eneg, ecoef, escale, 0)
+}
+
+// prodBint computes the product of decimals using *big.Int arithmetic.
+func prodBint(d ...Decimal) (Decimal, error) {
+	ecoef := getBint()
+	defer putBint(ecoef)
+
+	fcoef := getBint()
+	defer putBint(fcoef)
+
+	ecoef.setFint(One.coef)
+	escale := One.Scale()
+	eneg := One.IsNeg()
+
+	for _, f := range d {
+		fcoef.setFint(f.coef)
+
+		// Compute e = e * f
+		ecoef.mul(ecoef, fcoef)
+		eneg = eneg != f.IsNeg()
+		escale = escale + f.Scale()
+
+		// Intermediate truncation
+		if escale > bscale {
+			ecoef.rshDown(ecoef, escale-bscale)
+			escale = bscale
+		}
+
+		// Check if e >= 10^59
+		if ecoef.hasPrec(len(bpow10)) {
+			return Decimal{}, unknownOverflowError()
+		}
+	}
+
+	return newFromBint(eneg, ecoef, escale, 0)
+}
+
+// Mean returns the (possibly rounded) mean of decimals.
+// It computes (d1 + d2 + ... + dn) / n with at least double precision
+// during the intermediate rounding.
+//
+// Mean returns an error if:
+//   - no arguments are provided;
+//   - the integer part of the result has more than [MaxPrec] digits.
+func Mean(d ...Decimal) (Decimal, error) {
+	// Special cases
+	switch len(d) {
+	case 0:
+		return Decimal{}, fmt.Errorf("computing [mean([])]: %w", errInvalidOperation)
+	case 1:
+		return d[0], nil
+	}
+
+	// General case
+	e, err := meanFint(d...)
+	if err != nil {
+		e, err = meanBint(d...)
+		if err != nil {
+			return Decimal{}, fmt.Errorf("computing [mean(%v)]: %w", d, err)
+		}
+	}
+
+	// Preferred scale
+	scale := 0
+	for _, f := range d {
+		scale = max(scale, f.Scale())
+	}
+	e = e.Trim(scale)
+
+	return e, nil
+}
+
+// meanFint computes the mean of decimals using uint64 arithmetic.
+func meanFint(d ...Decimal) (Decimal, error) {
+	ecoef := Zero.coef
+	escale := Zero.Scale()
+	eneg := Zero.IsNeg()
+
+	ncoef := fint(len(d))
+
+	for _, f := range d {
+		fcoef := f.coef
+
+		// Alignment
+		var ok bool
+		switch {
+		case escale > f.Scale():
+			fcoef, ok = fcoef.lsh(escale - f.Scale())
+			if !ok {
+				return Decimal{}, errDecimalOverflow
+			}
+		case escale < f.Scale():
+			ecoef, ok = ecoef.lsh(f.Scale() - escale)
+			if !ok {
+				return Decimal{}, errDecimalOverflow
+			}
+			escale = f.Scale()
+		}
+
+		// Compute e = e + f
+		if eneg == f.IsNeg() {
+			ecoef, ok = ecoef.add(fcoef)
+			if !ok {
+				return Decimal{}, errDecimalOverflow
+			}
+		} else {
+			if fcoef > ecoef {
+				eneg = f.IsNeg()
+			}
+			ecoef = ecoef.subAbs(fcoef)
+		}
+	}
+
+	// Alignment
+	var ok bool
+	if shift := MaxPrec - ecoef.prec(); shift > 0 {
+		ecoef, ok = ecoef.lsh(shift)
+		if !ok {
+			return Decimal{}, errDecimalOverflow // Should never happen
+		}
+		escale = escale + shift
+	}
+
+	// Compute e = e / n
+	ecoef, ok = ecoef.quo(ncoef)
+	if !ok {
+		return Decimal{}, errInexactDivision
+	}
+
+	return newFromFint(eneg, ecoef, escale, 0)
+}
+
+// meanBint computes the mean of decimals using *big.Int arithmetic.
+func meanBint(d ...Decimal) (Decimal, error) {
+	ecoef := getBint()
+	defer putBint(ecoef)
+
+	fcoef := getBint()
+	defer putBint(fcoef)
+
+	ncoef := getBint()
+	defer putBint(ncoef)
+
+	ecoef.setFint(Zero.coef)
+	escale := Zero.Scale()
+	eneg := Zero.IsNeg()
+	ncoef.setInt64(int64(len(d)))
+
+	for _, f := range d {
+		fcoef.setFint(f.coef)
+
+		// Alignment
+		switch {
+		case escale > f.Scale():
+			fcoef.lsh(fcoef, escale-f.Scale())
+		case escale < f.Scale():
+			ecoef.lsh(ecoef, f.Scale()-escale)
+			escale = f.Scale()
+		}
+
+		// Compute e = e + f
+		if eneg == f.IsNeg() {
+			ecoef.add(ecoef, fcoef)
+		} else {
+			if fcoef.cmp(ecoef) > 0 {
+				eneg = f.IsNeg()
+			}
+			ecoef.subAbs(ecoef, fcoef)
+		}
+	}
+
+	// Alignment
+	ecoef.lsh(ecoef, bscale-escale)
+
+	// Compute e = e / n
+	ecoef.quo(ecoef, ncoef)
+
+	return newFromBint(eneg, ecoef, bscale, 0)
+}
+
+// Mul returns the (possibly rounded) product of decimals d and e.
+//
+// Mul returns an overflow error if the integer part of the result has
+// more than [MaxPrec] digits.
+func (d Decimal) Mul(e Decimal) (Decimal, error) {
+	return d.MulExact(e, 0)
+}
+
+// MulExact is similar to [Decimal.Mul], but it allows you to specify the number
+// of digits after the decimal point that should be considered significant.
+// If any of the significant digits are lost during rounding, the method will
+// return an overflow error.
+// This method is useful for financial calculations where the scale should be
+// equal to or greater than the currency's scale.
+func (d Decimal) MulExact(e Decimal, scale int) (Decimal, error) {
+	if scale < MinScale || scale > MaxScale {
+		return Decimal{}, fmt.Errorf("computing [%v * %v]: %w", d, e, errScaleRange)
+	}
+
+	// General case
+	f, err := d.mulFint(e, scale)
+	if err != nil {
+		f, err = d.mulBint(e, scale)
+		if err != nil {
+			return Decimal{}, fmt.Errorf("computing [%v * %v]: %w", d, e, err)
+		}
+	}
+	return f, nil
+}
+
+// mulFint computes the product of two decimals using uint64 arithmetic.
+func (d Decimal) mulFint(e Decimal, minScale int) (Decimal, error) {
+	dcoef := d.coef
+	dscale := d.Scale()
+	dneg := d.IsNeg()
+
+	ecoef := e.coef
+
+	// Compute d = d * e
+	dcoef, ok := dcoef.mul(ecoef)
+	if !ok {
+		return Decimal{}, errDecimalOverflow
+	}
+	dscale = dscale + e.Scale()
+	dneg = dneg != e.IsNeg()
+
+	return newFromFint(dneg, dcoef, dscale, minScale)
+}
+
+// mulBint computes the product of two decimals using *big.Int arithmetic.
+func (d Decimal) mulBint(e Decimal, minScale int) (Decimal, error) {
+	dcoef := getBint()
+	defer putBint(dcoef)
+
+	ecoef := getBint()
+	defer putBint(ecoef)
+
+	dcoef.setFint(d.coef)
+	dscale := d.Scale()
+	dneg := d.IsNeg()
+	ecoef.setFint(e.coef)
+
+	// Compute d = d * e
+	dcoef.mul(dcoef, ecoef)
+	dneg = dneg != e.IsNeg()
+	dscale = dscale + e.Scale()
+
+	return newFromBint(dneg, dcoef, dscale, minScale)
+}
+
+// Pow returns the (possibly rounded) decimal raised to the given decimal power.
+// If zero is raised to zero power then the result is one.
+//
+// Pow returns an error if:
+//   - the integer part of the result has more than [MaxPrec] digits;
+//   - zero is raised to a negative power;
+//   - negative is raised to a fractional power
+
+[NOTE: this saved copy holds the first 46,077 characters of a 90,114-character document — the rest could not be delivered in one step. What is below is exact; what is missing is missing. If the part you need is not here, fetch the specific section of the page directly rather than assuming it is absent.]
\ No newline at end of file
diff --git a/tmp/reference/search-decimal_go_module-f6681c58.txt b/tmp/reference/search-decimal_go_module-f6681c58.txt
new file mode 100644
index 0000000..6089c40
--- /dev/null
+++ b/tmp/reference/search-decimal_go_module-f6681c58.txt
@@ -0,0 +1,61 @@
+20 results:
+decimal package - github.com/govalues/decimal - Go Packages
+  https://pkg.go.dev/github.com/govalues/decimal
+  Package decimal <strong>implements decimal floating-point numbers with correct rounding</strong>.
+decimal package - github.com/shopspring/decimal - Go Packages
+  https://pkg.go.dev/github.com/shopspring/decimal
+  Modules with tagged versions give importers more predictable builds. ... When a project reaches major version v1 it is considered stable. ... Arbitrary-precision fixed-point decimal numbers in go.
+decimal package - github.com/ericlagergren/decimal - Go Packages
+  https://pkg.go.dev/github.com/ericlagergren/decimal
+  Package decimal <strong>provides a high-performance, arbitrary precision, floating-point decimal library</strong>.
+GitHub - shopspring/decimal: Arbitrary-precision fixed-point decimal numbers in Go · GitHub
+  https://github.com/shopspring/decimal
+  Arbitrary-precision fixed-point decimal numbers in go.
+decimal package - github.com/db47h/decimal - Go Packages
+  https://pkg.go.dev/github.com/db47h/decimal
+  Modules with tagged versions give importers more predictable builds. ... When a project reaches major version v1 it is considered stable. ... <strong>Package decimal implements arbitrary-precision decimal floating-point arithmetic for Go</strong>.
+decimal package - github.com/vkonstantin/decimal - Go Packages
+  https://pkg.go.dev/github.com/vkonstantin/decimal
+  Package decimal <strong>provides a high-performance, arbitrary precision, floating-point decimal library</strong>.
+decimal package - github.com/da0x/decimal - Go Packages
+  https://pkg.go.dev/github.com/da0x/decimal
+  Package decimal <strong>implements an arbitrary precision fixed-point decimal</strong>.
+decimal package - google.golang.org/genproto/googleapis/type/decimal - Go Packages
+  https://pkg.go.dev/google.golang.org/genproto/googleapis/type/decimal
+  ... Redistributable licenses place ... version v1 it is considered stable. ... This section is empty. ... This section is empty. <strong>type Decimal struct { // The decimal value, as a string</strong>....
+decimal package - github.com/luno/luno-go/decimal - Go Packages
+  https://pkg.go.dev/github.com/luno/luno-go/decimal
+  Modules with tagged versions give importers more predictable builds. ... When a project reaches major version v1 it is considered stable. ... This section is empty. ... This section is empty. type Decimal struct { // contains filtered or unexported fields }
+decimal package - github.com/dexon-foundation/decimal - Go Packages
+  https://pkg.go.dev/github.com/dexon-foundation/decimal
+  Package decimal <strong>implements an arbitrary precision fixed-point decimal</strong>.
+decimal package - github.com/strongo/decimal - Go Packages
+  https://pkg.go.dev/github.com/strongo/decimal
+  Modules with tagged versions give importers more predictable builds. ... When a project reaches major version v1 it is considered stable. ... Decimal 64 bit numbers implementation to represent money values in GoLang. Based on int64.
+decimal/go.mod at master · ericlagergren/decimal
+  https://github.com/ericlagergren/decimal/blob/master/go.mod
+  <strong>A high-performance, arbitrary-precision, floating-point decimal library</strong>. - decimal/go.mod at master · ericlagergren/decimal
+apd: An Arbitrary-Precision Decimal Package for Go | Cockroach Labs
+  https://www.cockroachlabs.com/blog/apd-arbitrary-precision-decimal-package/
+  With the release of CockroachDB beta-20170223, we’d like to announce a new arbitrary-precision decimal package for Go: apd. This package replaces the underlying implementation of the DECIMAL type in CockroachDB and is available for anyone to fork and use.
+decimal package - github.com/processout/decimal - Go Packages
+  https://pkg.go.dev/github.com/processout/decimal
+  Package decimal <strong>implements an arbitrary precision fixed-point decimal</strong>.
+decimal package - github.com/golibhub/decimal - Go Packages
+  https://pkg.go.dev/github.com/golibhub/decimal
+  Modules with tagged versions give importers more predictable builds. ... When a project reaches major version v1 it is considered stable. ... <strong>This package provides a decimal type that can represent decimal numbers with arbitrary precision</strong>.
+GitHub - db47h/decimal: An arbitrary-precision decimal floating-point arithmetic package for Go · GitHub
+  https://github.com/db47h/decimal
+  An arbitrary-precision decimal floating-point arithmetic package for Go - db47h/decimal
+GitHub - govalues/decimal: Correctly rounded decimals for Go · GitHub
+  https://github.com/govalues/decimal
+  Package decimal <strong>implements correctly rounded decimal floating-point numbers for Go</strong>.
+decimal package - github.com/cmars/decimal - Go Packages
+  https://pkg.go.dev/github.com/cmars/decimal
+  Modules with tagged versions give importers more predictable builds. ... When a project reaches major version v1 it is considered stable. ... Arbitrary-precision fixed-point decimal numbers in go.
+decimal package - go.charczuk.com/sdk/decimal - Go Packages
+  https://pkg.go.dev/go.charczuk.com/sdk/decimal
+  Modules with tagged versions give importers more predictable builds. ... When a project reaches major version v1 it is considered stable. ... This section is empty. This section is empty. This section is empty. ... Decimal is <strong>a fixed precision number with (4) digits of precision</strong>.
+decimal package - github.com/greatcloak/decimal - Go Packages
+  https://pkg.go.dev/github.com/greatcloak/decimal
+  Package decimal <strong>implements an arbitrary precision fixed-point decimal</strong>.
\ No newline at end of file
diff --git a/tmp/reference/search-github.com_govalues_decimal_go.mod-82233f9a.txt b/tmp/reference/search-github.com_govalues_decimal_go.mod-82233f9a.txt
new file mode 100644
index 0000000..9bf8af8
--- /dev/null
+++ b/tmp/reference/search-github.com_govalues_decimal_go.mod-82233f9a.txt
@@ -0,0 +1,61 @@
+20 results:
+GitHub - govalues/decimal: Correctly rounded decimals for Go · GitHub
+  https://github.com/govalues/decimal
+  Package decimal <strong>implements correctly rounded decimal floating-point numbers for Go</strong>. This package is designed specifically for use in transactional financial systems. BSON, JSON, XML, SQL - Implements the necessary interfaces for direct compatibility ...
+money/go.mod at main · govalues/money
+  https://github.com/govalues/money/blob/main/go.mod
+  module github.com/govalues/money ·  · go 1.22 ·  · require github.com/govalues/decimal v0.1.36
+decimal package - github.com/govalues/decimal - Go Packages
+  https://pkg.go.dev/github.com/govalues/decimal
+  After creating a decimal, you can perform various operations as shown below: package main import ( &quot;fmt&quot; &quot;github.com/govalues/decimal&quot; ) func main() { // Constructors d, _ := decimal.New(8, 0) // d = 8 e, _ := decimal.Parse(&quot;12.5&quot;) // e = 12.5 f, _ := decimal.NewFromFloat64(2.567) // f = 2.567 g, _ := decimal.NewFromInt64(7, 896, 3) // g = 7.896 // Arithmetic operations fmt.Println(d.Add(e)) // 8 + 12.5 fmt.Println(d.Sub(e)) // 8 - 12.5 fmt.Println(d.SubAbs(e)) // abs(8 - 12.5) fmt.Println(d.Mul(e)) // 8 * 12.5 fmt.Println(d.AddMul(e, f)) // 8 + 12.5 * 2.567 fmt.Println(d.SubMul(e, f)) // 8 -
+decimal package - github.com/shopspring/decimal - Go Packages
+  https://pkg.go.dev/github.com/shopspring/decimal
+  govalues/decimal - high performance, zero-allocation, low precision (19 digits)
+decimal/decimal.go at main · govalues/decimal
+  https://github.com/govalues/decimal/blob/main/decimal.go
+  return Decimal{}, Decimal{}, fmt.Errorf(&quot;computing [%v div %v] and [%v mod %v]: %w&quot;, d, e, d, e, err) ... // UnmarshalBSONValue supports the following [types]: Null, Double, String, 32-bit Integer, 64-bit Integer, and [Decimal128]. ... // [v2/bson.ValueUnmarshaler]: https://pkg.go.dev/go.mongodb.org/mongo-driver/v2/bson#ValueUnmarshaler
+GitHub - warrenguy/govalues-decimal: Immutable floating-point decimals for Go
+  https://github.com/warrenguy/govalues-decimal
+  Immutable floating-point decimals for Go. Contribute to warrenguy/govalues-decimal development by creating an account on GitHub.
+decimal/go.mod at master · ericlagergren/decimal
+  https://github.com/ericlagergren/decimal/blob/master/go.mod
+  <strong>A high-performance, arbitrary-precision, floating-point decimal library</strong>. - decimal/go.mod at master · ericlagergren/decimal
+GitHub - shopspring/decimal: Arbitrary-precision fixed-point decimal numbers in Go · GitHub
+  https://github.com/shopspring/decimal
+  govalues/decimal - <strong>high performance, zero-allocation, low precision (19 digits)</strong> greatcloak/decimal - fork focusing on billing and e-commerce web application related use cases, includes out-of-the-box BSON marshaling support · Because float64 ...
+https://github.com/govalues/decimal | Ecosyste.ms: Awesome
+  https://awesome.ecosyste.ms/projects/github.com/govalues/decimal
+  Immutable floating-point decimals for Go https://github.com/govalues/decimal
+github.com/govalues/decimal | Go
+  https://deps.dev/go/github.com/govalues/decimal/v0.1.36
+  You need to enable JavaScript to run this app
+Pull requests · govalues/decimal
+  https://github.com/govalues/decimal/pulls
+  Correctly rounded decimals for Go. Contribute to govalues/decimal development by creating an account on GitHub.
+decimal/go.mod at master · shopspring/decimal
+  https://github.com/shopspring/decimal/blob/master/go.mod
+  Arbitrary-precision fixed-point decimal numbers in Go - decimal/go.mod at master · shopspring/decimal
+decimal package - github.com/greatcloak/decimal - Go Packages
+  https://pkg.go.dev/github.com/greatcloak/decimal
+  Decimals behave like other go numbers types: even though a = b will not deep copy b into a, <strong>it is impossible to modify a Decimal</strong>, since all Decimal methods return new Decimals and do not modify the originals. The downside is that this causes extra allocations, so Decimal is less performant.
+GitHub - govalues/money: Correctly rounded monetary amounts and exchange rates for Go · GitHub
+  https://github.com/govalues/money
+  Correctness - Arithmetic operations are cross-validated against the cockroachdb/apd and shopspring/decimal packages through extensive fuzz testing. ... Create an amount using one of the constructors. After creating an amount, you can perform various operations as shown below: package main import ( &quot;fmt&quot; &quot;github.com/govalues/decimal&quot; &quot;github.com/govalues/money&quot; ) func main() { // Constructors a, _ := money.NewAmount(&quot;USD&quot;, 8, 0) // a = $8.00 b, _ := money.ParseAmount(&quot;USD&quot;, &quot;12.5&quot;) // b = $12.50 c, _ := money.NewAmountFromFloat64(&quot;USD&quot;, 2.567) // c = $2.567 d, _ := money.NewAmountFromInt64(&quot;USD
+money package - github.com/govalues/money - Go Packages
+  https://pkg.go.dev/github.com/govalues/money
+  Correctness - Arithmetic operations are cross-validated against the cockroachdb/apd and shopspring/decimal packages through extensive fuzz testing. ... Create an amount using one of the constructors. After creating an amount, you can perform various operations as shown below: package main import ( &quot;fmt&quot; &quot;github.com/govalues/decimal&quot; &quot;github.com/govalues/money&quot; ) func main() { // Constructors a, _ := money.NewAmount(&quot;USD&quot;, 8, 0) // a = $8.00 b, _ := money.ParseAmount(&quot;USD&quot;, &quot;12.5&quot;) // b = $12.50 c, _ := money.NewAmountFromFloat64(&quot;USD&quot;, 2.567) // c = $2.567 d, _ := money.NewAmountFromInt64(&quot;USD
+Handling Currency In Golang And Other Programming Language - DEV Community
+  https://dev.to/tentanganak/handling-currency-in-golang-and-other-programming-language-518h
+  A well-supported library with an active community can be crucial for getting help and finding solutions to problems. Look for libraries that are actively maintained and updated. This article will use 3rd party library govalues/decimal for code example, since doc simple and easy to read and suite the need for code demonstration · package main import ( &quot;fmt&quot; &quot;github.com/govalues/decimal&quot; ) func main() { a, _ := decimal.Parse(&quot;1.1&quot;) b, _ := decimal.Parse(&quot;1.2&quot;) c, _ := decimal.Parse(&quot;1.3&quot;) a, _ = a.Add(b) a, _ = a.Add(c) fmt.Println(a.String()) }
+decimal package - github.com/zzpierce/fast-decimal - Go Packages
+  https://pkg.go.dev/github.com/zzpierce/fast-decimal
+  After creating a decimal value, various operations can be performed: package main import ( &quot;fmt&quot; &quot;github.com/govalues/decimal&quot; ) func main() { // Constructors d, _ := decimal.New(8, 0) // d = 8 e, _ := decimal.Parse(&quot;12.5&quot;) // e = 12.5 f, _ := decimal.NewFromFloat64(2.567) // f = 2.567 g, _ := decimal.NewFromInt64(7, 896, 3) // g = 7.896 // Operations fmt.Println(d.Add(e)) // 8 + 12.5 fmt.Println(d.Sub(e)) // 8 - 12.5 fmt.Println(d.Mul(e)) // 8 * 12.5 fmt.Println(d.FMA(e, f)) // 8 * 12.5 + 2.567 fmt.Println(d.Pow(2)) // 8² fmt.Println(d.Sqrt()) // √8 fmt.Println(d.Quo(e)) // 8 ÷ 12.5 fmt.P
+decimal/decimal.go at v1.4.0 · shopspring/decimal
+  https://github.com/shopspring/decimal/blob/v1.4.0/decimal.go
+  // instead compare 2 r 10 ^precision and d2 · 	var rv2 big.Int · 	rv2.Abs(r.value) 	rv2.Lsh(&amp;rv2, 1) 	// now rv2 = abs(r.value) * 2 · 	r2 := Decimal{value: &amp;rv2, exp: r.exp + precision} 	// r2 is now 2 * r * 10 ^ precision · 	var c = r2.Cmp(d2.Abs())  · 	if c &lt; 0 { 		return q · 	}  · 	if d.value.Sign()*d2.value.Sign() &lt; 0 { 		return q.Sub(New(1, -precision)) 	}  · 	return q.Add(New(1, -precision)) }  · // Mod returns d % d2.
+decimal/decimal.go at master · shopspring/decimal
+  https://github.com/shopspring/decimal/blob/master/decimal.go
+  // instead compare 2 r 10 ^precision and d2 · 	var rv2 big.Int · 	rv2.Abs(r.getValue()) 	rv2.Lsh(&amp;rv2, 1) 	// now rv2 = abs(r.value) * 2 · 	r2 := Decimal{value: &amp;rv2, exp: r.exp + precision} 	// r2 is now 2 * r * 10 ^ precision · 	var c = r2.Cmp(d2.Abs())  · 	if c &lt; 0 { 		return q · 	}  · 	if d.getValue().Sign()*d2.getValue().Sign() &lt; 0 { 		return q.Sub(New(1, -precision)) 	}  · 	return q.Add(New(1, -precision)) }  · // Mod returns d % d2.
+r/golang on Reddit: list of decimal packages: fixed and big
+  https://www.reddit.com/r/golang/comments/1iuunf1/list_of_decimal_packages_fixed_and_big/
+  https://pkg.go.dev/github.com/anz-bank/decimal#Decimal64 (fixed size, 64) https://pkg.go.dev/github.com/govalues/decimal#Decimal (fixed size, 64) https://pkg.go.dev/github.com/jokruger/dec128#Dec128 (fixed size, 128) https://pkg.go.dev/github.com/cockroachdb/apd#Decimal (big dec) https://pkg.go.dev/github.com/ericlagergren/decimal#Big (big dec) https://pkg.go.dev/github.com/quagmt/udecimal#Decimal (big dec, hybrid storage) https://pkg.go.dev/github.com/amazon-ion/ion-go/ion#Decimal (big dec) https://pkg.go.dev/github.com/alpacahq/alpacadecimal#Decimal (big dec, hybrid storage) https://pkg.go.d
\ No newline at end of file
diff --git a/tmp/reference/search-github.com_govalues_decimal_quantize-cd37b0c8.txt b/tmp/reference/search-github.com_govalues_decimal_quantize-cd37b0c8.txt
new file mode 100644
index 0000000..54ec125
--- /dev/null
+++ b/tmp/reference/search-github.com_govalues_decimal_quantize-cd37b0c8.txt
@@ -0,0 +1,61 @@
+20 results:
+decimal package - github.com/govalues/decimal - Go Packages
+  https://pkg.go.dev/github.com/govalues/decimal
+  package main import ( &quot;fmt&quot; ...stParse(&quot;0.4&quot;) fmt.Println(d.Prec()) fmt.Println(e.Prec()) fmt.Println(f.Prec()) } ... <strong>Quantize returns a decimal rescaled to the same scale as decimal e</strong>....
+GitHub - govalues/decimal: Correctly rounded decimals for Go · GitHub
+  https://github.com/govalues/decimal
+  Package decimal <strong>implements correctly rounded decimal floating-point numbers for Go</strong>. This package is designed specifically for use in transactional financial systems. BSON, JSON, XML, SQL - Implements the necessary interfaces for direct compatibility ...
+decimal package - github.com/vkonstantin/decimal - Go Packages
+  https://pkg.go.dev/github.com/vkonstantin/decimal
+  Quantize <strong>sets z to the number equal in value and sign to z with the scale, n</strong>. The rounding of z is performed according to the rounding mode set in z.Context.RoundingMode. In order to perform truncation, set z.Context.RoundingMode to ToZero. ... package main import ( &quot;fmt&quot; &quot;github.com/vkons...
+decimal package - github.com/zzpierce/fast-decimal - Go Packages
+  https://pkg.go.dev/github.com/zzpierce/fast-decimal
+  package main import ( &quot;fmt&quot; decimal ...stParse(&quot;0.4&quot;) fmt.Println(d.Prec()) fmt.Println(e.Prec()) fmt.Println(f.Prec()) } ... <strong>Quantize returns a decimal rescaled to the same scale as decimal e</strong>....
+decimal package - github.com/ericlagergren/decimal - Go Packages
+  https://pkg.go.dev/github.com/ericlagergren/decimal
+  Quantize <strong>sets z to the number equal in value and sign to z with the scale, n</strong>.
+github.com/govalues/decimal | Go
+  https://deps.dev/go/github.com/govalues/decimal/v0.1.36
+  You need to enable JavaScript to run this app
+GitHub - govalues/decimal-tests: Benchmarks and fuzz tests for decimal package · GitHub
+  https://github.com/govalues/decimal-tests
+  <strong>This repository contains tests and benchmarks for the decimal arithmetic library govalues/decimal</strong>. ... go install golang.org/x/perf/cmd/benchstat@latest go install github.com/go-task/task/v3/cmd/task@latest
+money package - github.com/govalues/money - Go Packages
+  https://pkg.go.dev/github.com/govalues/money
+  Correctness - Arithmetic operations are cross-validated against the cockroachdb/apd and shopspring/decimal packages through extensive fuzz testing. ... Create an amount using one of the constructors. After creating an amount, you can perform various operations as shown below: package main import ( &quot;fmt&quot; &quot;github.com/govalues/decimal&quot; &quot;github.com/govalues/money&quot; ) func main() { // Constructors a, _ := money.NewAmount(&quot;USD&quot;, 8, 0) // a = $8.00 b, _ := money.ParseAmount(&quot;USD&quot;, &quot;12.5&quot;) // b = $12.50 c, _ := money.NewAmountFromFloat64(&quot;USD&quot;, 2.567) // c = $2.567 d, _ := money.NewAmountFromInt64(&quot;USD
+GitHub - govalues/money: Correctly rounded monetary amounts and exchange rates for Go · GitHub
+  https://github.com/govalues/money
+  Correctness - Arithmetic operations are cross-validated against the cockroachdb/apd and shopspring/decimal packages through extensive fuzz testing. ... Create an amount using one of the constructors. After creating an amount, you can perform various operations as shown below: package main import ( &quot;fmt&quot; &quot;github.com/govalues/decimal&quot; &quot;github.com/govalues/money&quot; ) func main() { // Constructors a, _ := money.NewAmount(&quot;USD&quot;, 8, 0) // a = $8.00 b, _ := money.ParseAmount(&quot;USD&quot;, &quot;12.5&quot;) // b = $12.50 c, _ := money.NewAmountFromFloat64(&quot;USD&quot;, 2.567) // c = $2.567 d, _ := money.NewAmountFromInt64(&quot;USD
+decimal/decimal.go at main · govalues/decimal
+  https://github.com/govalues/decimal/blob/main/decimal.go
+  return Decimal{}, fmt.Errorf(&quot;computing [%v^%v]: %w: zero to negative power&quot;, d, e, errInvalidOperation)
+decimal package - github.com/shopspring/decimal - Go Packages
+  https://pkg.go.dev/github.com/shopspring/decimal
+  Note: Decimal library can &quot;only&quot; represent numbers with a maximum of 2^31 digits after the decimal point. The zero-value is 0, and is safe to use without initialization · Addition, subtraction, multiplication with no loss of precision ... package main import ( &quot;fmt&quot; &quot;github.com/shopspring/decimal&quot; ) func main() { price, err := decimal.NewFromString(&quot;136.02&quot;) if err != nil { panic(err) } quantity := decimal.NewFromInt(3) fee, _ := decimal.NewFromString(&quot;.035&quot;) taxRate, _ := decimal.NewFromString(&quot;.08875&quot;) subtotal := price.Mul(quantity) preTax := subtotal.Mul(fee.Add(decimal.NewFromFloat(1)))
+decimal package - github.com/db47h/decimal - Go Packages
+  https://pkg.go.dev/github.com/db47h/decimal
+  As a consequence to points (1) and (2), and unlike in the IEEE-754 standard, a finite Decimal can only be a normal number (no subnormal numbers) and <strong>there is no Quantize operation</strong>.
+https://github.com/govalues/decimal | Ecosyste.ms: Awesome
+  https://awesome.ecosyste.ms/projects/github.com/govalues/decimal
+  Immutable floating-point decimals for Go https://github.com/govalues/decimal
+GitHub - warrenguy/govalues-decimal: Immutable floating-point decimals for Go
+  https://github.com/warrenguy/govalues-decimal
+  After creating a decimal, you can perform various operations as shown below: package main import ( &quot;fmt&quot; &quot;github.com/govalues/decimal&quot; ) func main() { // Constructors d, _ := decimal.New(8, 0) // d = 8 e, _ := decimal.Parse(&quot;12.5&quot;) // e = 12.5 f, _ := decimal.NewFromFloat64(2.567) // f = 2.567 g, _ := decimal.NewFromInt64(7, 896, 3) // g = 7.896 // Arithmetic operations fmt.Println(d.Add(e)) // 8 + 12.5 fmt.Println(d.Sub(e)) // 8 - 12.5 fmt.Println(d.SubAbs(e)) // abs(8 - 12.5) fmt.Println(d.Mul(e)) // 8 * 12.5 fmt.Println(d.AddMul(e, f)) // 8 + 12.5 * 2.567 fmt.Println(d.SubMul(e, f)) // 8 -
+Pull requests · govalues/decimal
+  https://github.com/govalues/decimal/pulls
+  Correctly rounded decimals for Go. Contribute to govalues/decimal development by creating an account on GitHub.
+GitHub - shopspring/decimal: Arbitrary-precision fixed-point decimal numbers in Go · GitHub
+  https://github.com/shopspring/decimal
+  alpacahq/alpacadecimal - high performance, low precision (12 digits), fully compatible API with this library · govalues/decimal - <strong>high performance, zero-allocation, low precision (19 digits)</strong>
+til/python/decimal_quantize.md at main · williln/til
+  https://github.com/williln/til/blob/main/python/decimal_quantize.md
+  decimal — Decimal fixed point and floating point arithmetic — Python 3.12.4 documentation ... The quantize() method <strong>rounds a number to a fixed exponent</strong>.
+money/CHANGELOG.md at main · govalues/money
+  https://github.com/govalues/money/blob/main/CHANGELOG.md
+  ExchangeRate.Decimal, ExchangeRate.Ceil, ExchangeRate.Floor, ExchangeRate.Trunc, ExchangeRate.Trim. ExchangeRate.IsPos, ExchangeRate.Sign, ExchangeRate.MinScale, ExchangeRate.Quantize, Implemented NullCurrency type. Renamed NewAmount contructor to NewAmountFromDecimal.
+Handling Currency In Golang And Other Programming Language - DEV Community
+  https://dev.to/tentanganak/handling-currency-in-golang-and-other-programming-language-518h
+  A well-supported library with an active community can be crucial for getting help and finding solutions to problems. Look for libraries that are actively maintained and updated. This article will use 3rd party library govalues/decimal for code example, since doc simple and easy to read and suite the need for code demonstration · package main import ( &quot;fmt&quot; &quot;github.com/govalues/decimal&quot; ) func main() { a, _ := decimal.Parse(&quot;1.1&quot;) b, _ := decimal.Parse(&quot;1.2&quot;) c, _ := decimal.Parse(&quot;1.3&quot;) a, _ = a.Add(b) a, _ = a.Add(c) fmt.Println(a.String()) }
+Decimal('0.0000005').quantize(Decimal('1.1111111')) -> Decimal('5E-7') # should be unchanged · Issue #128373 · python/cpython
+  https://github.com/python/cpython/issues/128373
+  According to the documentation, https://docs.python.org/3/library/decimal.html#decimal.Decimal.quantize quantize() should &quot;<strong>Return a value equal to the first operand after rounding and having the exponent of the second operand</strong>.&quot;
\ No newline at end of file
diff --git a/tmp/reference/search-github.com_govalues_decimal_readme-d95c4e98.txt b/tmp/reference/search-github.com_govalues_decimal_readme-d95c4e98.txt
new file mode 100644
index 0000000..f45289e
--- /dev/null
+++ b/tmp/reference/search-github.com_govalues_decimal_readme-d95c4e98.txt
@@ -0,0 +1,61 @@
+20 results:
+GitHub - govalues/decimal: Correctly rounded decimals for Go · GitHub
+  https://github.com/govalues/decimal
+  After creating a decimal, you can perform various operations as shown below: package main import ( &quot;fmt&quot; &quot;github.com/govalues/decimal&quot; ) func main() { // Constructors d, _ := decimal.New(8, 0) // d = 8 e, _ := decimal.Parse(&quot;12.5&quot;) // e = 12.5 f, _ := decimal.NewFromFloat64(2.567) // f = 2.567 g, _ := decimal.NewFromInt64(7, 896, 3) // g = 7.896 // Arithmetic operations fmt.Println(d.Add(e)) // 8 + 12.5 fmt.Println(d.Sub(e)) // 8 - 12.5 fmt.Println(d.SubAbs(e)) // abs(8 - 12.5) fmt.Println(d.Mul(e)) // 8 * 12.5 fmt.Println(d.AddMul(e, f)) // 8 + 12.5 * 2.567 fmt.Println(d.SubMul(e, f)) // 8 -
+decimal package - github.com/govalues/decimal - Go Packages
+  https://pkg.go.dev/github.com/govalues/decimal
+  In decimal arithmetic, the result is exactly 0.3, as expected. In float64 arithmetic, the result is 0.30000000000000004 due to floating-point inaccuracy. package main import ( &quot;fmt&quot; &quot;github.com/govalues/decimal&quot; ) func main() { a := decimal.MustParse(&quot;0.1&quot;) b := decimal.MustParse(&quot;0.2&quot;) fmt.Println(a.Add(b)) x := 0.1 y := 0.2 fmt.Println(x + y) }
+https://github.com/govalues/decimal | Ecosyste.ms: Awesome
+  https://awesome.ecosyste.ms/projects/github.com/govalues/decimal
+  Homepage: https://pkg.go.dev/g... Readme: README.md · Changelog: CHANGELOG.md · License: LICENSE · awesome-go - decimal - <strong>Immutable decimal numbers with panic-free arithmetic</strong>....
+decimal package - github.com/shopspring/decimal - Go Packages
+  https://pkg.go.dev/github.com/shopspring/decimal
+  govalues/decimal - high performance, zero-allocation, low precision (19 digits)
+decimal/README.md at master · shopspring/decimal
+  https://github.com/shopspring/decimal/blob/master/README.md
+  alpacahq/alpacadecimal - high performance, low precision (12 digits), fully compatible API with this library · govalues/decimal - high performance, zero-allocation, low precision (19 digits)
+decimal/decimal.go at main · govalues/decimal
+  https://github.com/govalues/decimal/blob/main/decimal.go
+  Correctly rounded decimals for Go. Contribute to govalues/decimal development by creating an account on GitHub.
+GitHub - shopspring/decimal: Arbitrary-precision fixed-point decimal numbers in Go · GitHub
+  https://github.com/shopspring/decimal
+  alpacahq/alpacadecimal - high performance, low precision (12 digits), fully compatible API with this library · govalues/decimal - high performance, zero-allocation, low precision (19 digits)
+GitHub - warrenguy/govalues-decimal: Immutable floating-point decimals for Go
+  https://github.com/warrenguy/govalues-decimal
+  After creating a decimal, you can perform various operations as shown below: package main import ( &quot;fmt&quot; &quot;github.com/govalues/decimal&quot; ) func main() { // Constructors d, _ := decimal.New(8, 0) // d = 8 e, _ := decimal.Parse(&quot;12.5&quot;) // e = 12.5 f, _ := decimal.NewFromFloat64(2.567) // f = 2.567 g, _ := decimal.NewFromInt64(7, 896, 3) // g = 7.896 // Arithmetic operations fmt.Println(d.Add(e)) // 8 + 12.5 fmt.Println(d.Sub(e)) // 8 - 12.5 fmt.Println(d.SubAbs(e)) // abs(8 - 12.5) fmt.Println(d.Mul(e)) // 8 * 12.5 fmt.Println(d.AddMul(e, f)) // 8 + 12.5 * 2.567 fmt.Println(d.SubMul(e, f)) // 8 -
+github.com/govalues/decimal | Go
+  https://deps.dev/go/github.com/govalues/decimal/v0.1.36
+  You need to enable JavaScript to run this app
+GitHub - govalues/decimal-tests: Benchmarks and fuzz tests for decimal package · GitHub
+  https://github.com/govalues/decimal-tests
+  <strong>This repository contains tests and benchmarks for the decimal arithmetic library govalues/decimal</strong>. ... go install golang.org/x/perf/cmd/benchstat@latest go install github.com/go-task/task/v3/cmd/task@latest
+Pull requests · govalues/decimal
+  https://github.com/govalues/decimal/pulls
+  Correctly rounded decimals for Go. Contribute to govalues/decimal development by creating an account on GitHub.
+decimal package - github.com/zzpierce/fast-decimal - Go Packages
+  https://pkg.go.dev/github.com/zzpierce/fast-decimal
+  After creating a decimal value, various operations can be performed: package main import ( &quot;fmt&quot; &quot;github.com/govalues/decimal&quot; ) func main() { // Constructors d, _ := decimal.New(8, 0) // d = 8 e, _ := decimal.Parse(&quot;12.5&quot;) // e = 12.5 f, _ := decimal.NewFromFloat64(2.567) // f = 2.567 g, _ := decimal.NewFromInt64(7, 896, 3) // g = 7.896 // Operations fmt.Println(d.Add(e)) // 8 + 12.5 fmt.Println(d.Sub(e)) // 8 - 12.5 fmt.Println(d.Mul(e)) // 8 * 12.5 fmt.Println(d.FMA(e, f)) // 8 * 12.5 + 2.567 fmt.Println(d.Pow(2)) // 8² fmt.Println(d.Sqrt()) // √8 fmt.Println(d.Quo(e)) // 8 ÷ 12.5 fmt.P
+money package - github.com/govalues/money - Go Packages
+  https://pkg.go.dev/github.com/govalues/money
+  <strong>NewAmountFromDecimal returns an error if the integer part of the result has more than (decimal.</strong>MaxPrec - Currency.Scale) digits. For example, when currency is US Dollars, NewAmountFromDecimal will return an error if the integer part of the result has more than 17 digits (19 - 2 = 17).
+decimal package - github.com/processout/decimal - Go Packages
+  https://pkg.go.dev/github.com/processout/decimal
+  NOTE: can &quot;only&quot; represent numbers with a maximum of 2^31 digits after the decimal point. the zero-value is 0, and is safe to use without initialization · addition, subtraction, multiplication with no loss of precision ... package main import ( &quot;fmt&quot; &quot;github.com/shopspring/decimal&quot; ) func main() { price, err := decimal.NewFromString(&quot;136.02&quot;) if err != nil { panic(err) } quantity := decimal.NewFromFloat(3) fee, _ := decimal.NewFromString(&quot;.035&quot;) taxRate, _ := decimal.NewFromString(&quot;.08875&quot;) subtotal := price.Mul(quantity) preTax := subtotal.Mul(fee.Add(decimal.NewFromFloat(1))) total := preTa
+decimal package - github.com/golibhub/decimal - Go Packages
+  https://pkg.go.dev/github.com/golibhub/decimal
+  Decimal.Div method uses a default precision of 32, which can be customized by setting a new value to DivPrecision variable.
+decimal package - github.com/greatcloak/decimal - Go Packages
+  https://pkg.go.dev/github.com/greatcloak/decimal
+  govalues/decimal - high performance, zero-allocation, low precision (19 digits)
+decimals/readme.md at master · olihawkins/decimals
+  https://github.com/olihawkins/decimals/blob/master/readme.md
+  <strong>Decimals is a small library of functions for rounding and formatting base ten numbers in Go</strong>. - olihawkins/decimals
+decimal package - github.com/ericlagergren/decimal - Go Packages
+  https://pkg.go.dev/github.com/ericlagergren/decimal
+  Useful zero values. The zero value of a decimal.Big is 0, just like math/big.
+r/golang on Reddit: list of decimal packages: fixed and big
+  https://www.reddit.com/r/golang/comments/1iuunf1/list_of_decimal_packages_fixed_and_big/
+  https://pkg.go.dev/github.com/anz-bank/decimal#Decimal64 (fixed size, 64) https://pkg.go.dev/github.com/govalues/decimal#Decimal (fixed size, 64)
+decimal package - github.com/strongo/decimal - Go Packages
+  https://pkg.go.dev/github.com/strongo/decimal
+  At the moment <strong>provides just a single type Decimal64p2 with fixed precision of 2 digits after point</strong>. In simple words it stores value as 64 bits integer amount of cents. The code has 100% unit tests coverage. E.g. 1.43 will be stored as int64(143) but when rendered as string will be represented ...
\ No newline at end of file

```
