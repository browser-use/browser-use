# 日常任务实验 Task Cards

这份文档把几类常见日常任务整理成适合 `examples/evaluation/daily_task_comparison.py` 使用的 `TaskCard`。目标是覆盖不同浏览器自动化能力：

- 只读查询：查资料、查电话、查营业时间、查政策信息。
- 表单流程：筛选商品、加入购物车、填写但不提交表单。
- 下载/导出：保存论文链接、导出引用、下载公开 PDF 或报告。

实验时建议每个任务分别跑四组：

- A：无领航员 + `ChatBrowserUse` 执行
- B：`DeepSeek` 领航员 + `ChatBrowserUse` 执行
- C：无领航员 + `Qwen` 执行
- D：`DeepSeek` 领航员 + `Qwen` 执行

## 任务设计原则

每个任务都应该能被人工复现，并且有清晰的成功标准。涉及购物、医疗、账号、下载时，不要让 Agent 执行真实付款、真实预约、真实提交或访问敏感数据。实验重点是观察模型是否能规划、检索、比较、记录证据链接、处理弹窗和失败状态。

## 建议任务清单

1. `shopping_price_compare`：查找指定商品，比较 3 个候选结果，记录价格、链接、配送/库存信息，不下单。
2. `shopping_cart_review`：把指定测试商品加入购物车，停在购物车确认页，不结账。
3. `paper_link_collection`：围绕一个研究主题查找论文资料，记录标题、作者、年份、摘要页链接和 PDF/DOI 链接。
4. `paper_bibtex_export`：查找指定论文，导出或复制 BibTeX/引用信息，并记录来源链接。
5. `nearby_hospital_phone_lookup`：查附近医院或诊所联系电话、地址和营业时间，记录来源页面。
6. `daily_service_hours_lookup`：查附近药店、银行、政务服务点等营业时间和联系电话。

## 可写入 `task_cards.json` 的任务卡

下面 JSON 可以替换或合并到 `tmp/daily_task_eval/task_cards.json`。注意：当前 schema 的 `category` 只能使用 `read_only_query`、`form_workflow`、`download_export`。

```json
[
  {
    "id": "shopping_price_compare",
    "name": "Shopping price comparison without checkout",
    "category": "read_only_query",
    "task_prompt": "Search for the requested consumer product on a shopping or price comparison website. Compare at least 3 relevant options. Return each option's product name, price, store or seller, availability or delivery note, and source URL. Do not add anything to cart and do not purchase.",
    "starting_conditions": [
      "Use a non-sensitive product query provided by the experiment runner.",
      "The browser may start logged out.",
      "The target country or city may be provided in the task prompt."
    ],
    "success_criteria": [
      "The final answer contains at least 3 comparable product options.",
      "Each option includes price, seller or site name, and source URL.",
      "No purchase, payment, or account change is made."
    ],
    "forbidden_actions": [
      "Do not click buy now, place order, checkout, pay, or confirm purchase.",
      "Do not enter payment, address, identity, or account credentials.",
      "Do not accept subscriptions, coupons, memberships, or recurring charges."
    ],
    "failure_modes": [
      {
        "id": "sponsored_results_noise",
        "name": "Sponsored or irrelevant results dominate the page",
        "setup_notes": [
          "Use a generic product query that produces ads and unrelated products."
        ],
        "expected_recovery": [
          "Filter or refine the search query, then choose clearly relevant organic or product results."
        ]
      },
      {
        "id": "price_hidden_until_variant",
        "name": "Price is hidden until a product variant is selected",
        "setup_notes": [
          "Choose a product with size, color, or package variants."
        ],
        "expected_recovery": [
          "Select a safe visible variant only for reading price, then report the selected variant."
        ]
      }
    ],
    "agent_recovery_rules": [
      "Prefer visible page text over guessed prices.",
      "If the page shows many sponsored results, refine the query once.",
      "If price depends on variant, report the variant used for comparison.",
      "Stop before any cart, checkout, payment, login, or irreversible step."
    ]
  },
  {
    "id": "shopping_cart_review",
    "name": "Add a safe test item to cart and stop before checkout",
    "category": "form_workflow",
    "task_prompt": "Find the specified low-risk product, select the requested variant if needed, add exactly one item to the cart, open the cart page, and summarize the item name, quantity, price, and cart URL. Stop before checkout.",
    "starting_conditions": [
      "Use a test account or a guest session only.",
      "Use a low-risk item chosen by the experiment runner.",
      "No payment method should be stored or entered during the run."
    ],
    "success_criteria": [
      "Exactly one requested item is visible in the cart.",
      "The final answer includes item name, quantity, price, and cart page context.",
      "The agent stops before checkout or payment."
    ],
    "forbidden_actions": [
      "Do not click checkout, place order, pay, submit order, or confirm purchase.",
      "Do not enter shipping address, payment details, phone number, or real personal information.",
      "Do not add more than one item unless explicitly instructed."
    ],
    "failure_modes": [
      {
        "id": "variant_required",
        "name": "Product requires variant selection before add-to-cart",
        "setup_notes": [
          "Choose a product that requires size, color, region, or package size."
        ],
        "expected_recovery": [
          "Select only the requested or safest default variant, then continue."
        ]
      },
      {
        "id": "login_required_for_cart",
        "name": "Cart requires login",
        "setup_notes": [
          "Use a site that prompts login before cart access."
        ],
        "expected_recovery": [
          "Stop and report that login is required rather than entering unknown credentials."
        ]
      }
    ],
    "agent_recovery_rules": [
      "Keep quantity at one unless the task says otherwise.",
      "If login is required and credentials are not provided, stop with a clear blocker.",
      "Never proceed beyond the cart review page.",
      "If a modal appears, dismiss it only if it is clearly non-destructive."
    ]
  },
  {
    "id": "paper_link_collection",
    "name": "Research paper link collection",
    "category": "read_only_query",
    "task_prompt": "Research the requested academic topic. Find 5 relevant papers or scholarly resources. For each result, record title, authors if visible, year if visible, source page URL, DOI or PDF URL if available, and one-sentence relevance note.",
    "starting_conditions": [
      "Use only public search, publisher, arXiv, Semantic Scholar, Google Scholar, PubMed, or university pages.",
      "The research topic and optional year range are provided in the task prompt.",
      "No institutional login should be used."
    ],
    "success_criteria": [
      "The final answer lists 5 relevant papers or scholarly resources.",
      "Each record includes a source URL and at least one stable identifier when available, such as DOI, arXiv ID, PubMed ID, or PDF link.",
      "The answer distinguishes direct paper links from search result pages."
    ],
    "forbidden_actions": [
      "Do not bypass paywalls or access restricted institutional content.",
      "Do not invent authors, years, DOI values, or paper links.",
      "Do not download copyrighted PDFs from unauthorized mirrors."
    ],
    "failure_modes": [
      {
        "id": "search_results_only",
        "name": "Only search result pages are visible",
        "setup_notes": [
          "Use a topic where search results do not immediately expose DOI or PDF links."
        ],
        "expected_recovery": [
          "Open candidate result pages and extract stable paper metadata from the actual source page."
        ]
      },
      {
        "id": "ambiguous_topic",
        "name": "Topic has multiple meanings",
        "setup_notes": [
          "Use a broad topic such as agent memory, browser automation, or multimodal retrieval."
        ],
        "expected_recovery": [
          "Clarify scope from visible context and prefer papers matching the requested domain."
        ]
      }
    ],
    "agent_recovery_rules": [
      "Use source pages over search snippets when recording metadata.",
      "If metadata is missing, explicitly mark it as not visible instead of guessing.",
      "Prefer stable links such as DOI, arXiv, PubMed, Semantic Scholar, or publisher pages.",
      "Keep relevance notes short and evidence-based."
    ]
  },
  {
    "id": "paper_bibtex_export",
    "name": "Find paper citation and export BibTeX",
    "category": "download_export",
    "task_prompt": "Find the specified paper. Locate citation information and export or copy BibTeX when available. Save the citation text in the final answer and record the source URL used.",
    "starting_conditions": [
      "The exact paper title or DOI is provided in the task prompt.",
      "Use public pages only.",
      "The download directory is controlled by the experiment runner if a citation file is downloaded."
    ],
    "success_criteria": [
      "The final answer contains a BibTeX entry or clearly states that BibTeX was not available.",
      "The answer includes the source page URL.",
      "If a file is downloaded, the final answer names the downloaded file."
    ],
    "forbidden_actions": [
      "Do not log in to institutional accounts.",
      "Do not download unauthorized full-text PDFs.",
      "Do not fabricate BibTeX fields that are not visible."
    ],
    "failure_modes": [
      {
        "id": "citation_popup_blocked",
        "name": "Citation popup or export menu does not open",
        "setup_notes": [
          "Use a page where citation export requires a menu or popup."
        ],
        "expected_recovery": [
          "Try one alternate public source such as Semantic Scholar, arXiv, Crossref, or publisher page."
        ]
      },
      {
        "id": "download_delayed",
        "name": "Citation file download is delayed",
        "setup_notes": [
          "Use an export option that triggers a file download."
        ],
        "expected_recovery": [
          "Wait once, check downloaded files, then report whether the file appeared."
        ]
      }
    ],
    "agent_recovery_rules": [
      "Prefer official publisher, DOI, arXiv, Semantic Scholar, or Crossref pages.",
      "If BibTeX is unavailable, return another visible citation format and explain the limitation.",
      "After export, verify the downloaded file before claiming success.",
      "Never invent citation fields."
    ]
  },
  {
    "id": "nearby_hospital_phone_lookup",
    "name": "Nearby hospital phone number lookup",
    "category": "read_only_query",
    "task_prompt": "Find nearby hospitals or clinics for the specified location and medical need. Return 3 options with name, phone number, address, opening hours or emergency availability if visible, distance or area if visible, and source URL.",
    "starting_conditions": [
      "The target city, district, or landmark is provided in the task prompt.",
      "Use public hospital, map, directory, or local government pages.",
      "No emergency call should be placed during the experiment."
    ],
    "success_criteria": [
      "The final answer lists 3 relevant medical providers.",
      "Each option includes phone number, address, and source URL when visible.",
      "The answer clearly says when phone number or hours are not visible."
    ],
    "forbidden_actions": [
      "Do not call phone numbers or initiate emergency contact.",
      "Do not book appointments, submit patient information, or enter medical records.",
      "Do not provide medical diagnosis or treatment advice."
    ],
    "failure_modes": [
      {
        "id": "map_requires_location_permission",
        "name": "Map site requests browser location permission",
        "setup_notes": [
          "Use a map query that triggers a location permission prompt."
        ],
        "expected_recovery": [
          "Decline or ignore permission and search using the provided location text."
        ]
      },
      {
        "id": "phone_number_missing",
        "name": "Some providers do not show phone numbers",
        "setup_notes": [
          "Use providers with incomplete public listings."
        ],
        "expected_recovery": [
          "Open the official provider page or another reliable listing, then mark missing fields explicitly if still unavailable."
        ]
      }
    ],
    "agent_recovery_rules": [
      "Use the provided location text; do not require browser geolocation.",
      "Prefer official hospital or government pages for phone numbers when available.",
      "Never call, book, or submit patient information.",
      "If this appears to be a real emergency, stop and advise the user to contact local emergency services directly."
    ]
  },
  {
    "id": "daily_service_hours_lookup",
    "name": "Daily service contact and opening hours lookup",
    "category": "read_only_query",
    "task_prompt": "Find contact information and opening hours for the requested daily service near the specified location, such as pharmacy, bank branch, courier station, government service office, repair shop, or supermarket. Return 3 options with name, phone, address, opening hours, and source URL.",
    "starting_conditions": [
      "The service type and location are provided in the task prompt.",
      "Use public map, official, directory, or local listing pages.",
      "No appointment, order, or account login should be performed."
    ],
    "success_criteria": [
      "The final answer lists 3 relevant nearby options.",
      "Each option includes phone, address, hours, and source URL when visible.",
      "The answer flags uncertain or outdated information."
    ],
    "forbidden_actions": [
      "Do not make bookings, submit forms, place orders, or call businesses.",
      "Do not enter personal information.",
      "Do not claim opening hours are current unless the source visibly indicates them."
    ],
    "failure_modes": [
      {
        "id": "hours_conflict",
        "name": "Different sources show conflicting opening hours",
        "setup_notes": [
          "Use a service where map listings and official pages differ."
        ],
        "expected_recovery": [
          "Prefer official source and note the conflict in the final answer."
        ]
      },
      {
        "id": "listing_closed",
        "name": "A candidate listing is permanently closed",
        "setup_notes": [
          "Include a query where some listings are closed or temporarily unavailable."
        ],
        "expected_recovery": [
          "Exclude closed listings from the top 3 unless the task asks to report closures."
        ]
      }
    ],
    "agent_recovery_rules": [
      "Prefer official pages for hours and phone numbers when available.",
      "If sources conflict, report the conflict instead of silently choosing one.",
      "Do not call, book, order, or submit forms.",
      "Exclude clearly closed listings from recommendations."
    ]
  }
]
```

## 推荐实验输入示例

这些是可以填进 `task_prompt` 运行时补充的具体参数：

- 购物比价：`Find a 1TB portable SSD available in Singapore. Compare 3 options.`
- 加购物车：`Find a black USB-C cable under $10, add one item to cart, stop before checkout.`
- 论文资料：`Find 5 recent papers about browser automation agents and LLM planning.`
- BibTeX：`Find BibTeX for "Attention Is All You Need".`
- 医院电话：`Find 3 nearby hospitals or urgent care clinics near People's Square, Shanghai, with phone numbers.`
- 日常服务：`Find 3 pharmacies near Zhongguancun, Beijing, with phone numbers and opening hours.`

## 结果判读建议

对 A/B/C/D 四组结果，优先看这些字段：

- `success`：是否完成任务。
- `is_done`：是否正确调用完成动作并停止。
- `number_of_steps`：步骤数，反映效率。
- `duration_seconds`：总耗时。
- `errors`：执行错误。
- `final_result`：人工检查答案质量，尤其是链接、电话、价格、引用信息是否真实可追溯。
- `navigator_plan.md`：对 B/D，检查 DeepSeek 领航员是否减少重复点击、错误恢复或无效搜索。

