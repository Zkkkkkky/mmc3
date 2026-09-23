# M05 剩余参考动作分析

结论：`passed=true`；普通上传确认仅预览 2 项，8×8 模板修正请求后晋级黄金 1 项，资源保存确认但截图回读不适用 4 项，无效参考上传 1 项，未解码 0 项。

| 动作 | 分类 | 动作专属差分 | 拼图脚本对 | 活动 CHR | 冷重开等于原值 |
|---|---|---:|---:|---:|---|
| `body_upload_bmp` | `reference_preview_only_confirmed` | 0 | 0 | 0 | true |
| `fragment_upload_bmp` | `reference_preview_only_confirmed` | 0 | 0 | 0 | true |
| `body_compressed_upload_bmp` | `reference_resource_save_confirmed_capture_mismatch` | 14965 | 14241 | 724 | false |
| `fragment_compressed_upload_bmp` | `reference_resource_save_confirmed_capture_mismatch` | 9086 | 8792 | 294 | false |
| `icon_upload_bmp` | `reference_upload_clears_target` | 56 | 0 | 56 | false |
| `main_clear_body` | `reference_clear_save_confirmed_capture_mismatch` | 2398 | 1727 | 671 | false |
| `main_clear_fragment` | `reference_clear_save_confirmed_capture_mismatch` | 1639 | 1444 | 195 | false |
| `body_puzzle_template_8x8` | `reference_save_promoted_after_request_correction` | 13524 | 13524 | 0 | false |

普通上传的主体与碎片输出 ROM SHA-256 完全相同，说明两次保存只产生共同归一化；
两项在全新进程重开后均恢复原预览，因此不应要求当前产品复刻一个不存在的持久化协议。
全部动作专属偏移均已定位到机体拼图脚本对或活动 CHR：8×8 模板只改脚本对，图标上传只改 CHR，压缩上传与两项清除同时改脚本对和 CHR。
8×8 模板冷重开脚本正确，14.735 秒运行已晋级黄金；两项压缩上传与两项清除已由资源字节确认，图标上传确认保存为全零无效结果；未解码动作已清零。
