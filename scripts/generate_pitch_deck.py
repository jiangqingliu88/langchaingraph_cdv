from pptx import Presentation
from pptx.util import Inches, Pt

slides = [
    {
        "title": "SignOffAI — IC 验证与签核平台",
        "content": [
            "面向数字芯片功能验证与签核的企业级平台",
            "将验证流程变成可复现、可审计、可治理的工程流程。"
        ]
    },
    {
        "title": "问题痛点",
        "content": [
            "验证流程碎片化，规格、测试、回归、签核不连通。",
            "签核缺少证据链，企业难以审计、复现和合规。",
            "现有 AI 工具只能生成代码，无法满足企业级治理。"
        ]
    },
    {
        "title": "解决方案",
        "content": [
            "从规格到签核的端到端验证流程平台。",
            "自动生成验证计划、测试、断言、回归结果、覆盖率分析、签核报告。",
            "支持项目隔离、RBAC、审计日志与审批流。"
        ]
    },
    {
        "title": "核心价值",
        "content": [
            "可复现验证证据链：每一步产物、日志、数据库记录、报告可回溯。",
            "企业级签核交付：交付签核证据包而非单纯代码。",
            "治理与审计：满足半导体企业的合规与管理需求。"
        ]
    },
    {
        "title": "目标客户",
        "content": [
            "芯片设计公司验证团队。",
            "ASIC/FPGA IP 厂商与验证外包公司。",
            "EDA 厂商与 IDM 研发验证部门。"
        ]
    },
    {
        "title": "市场机会",
        "content": [
            "TAM：50–100 亿美元。",
            "SAM：5–20 亿美元。",
            "SOM：0.5–20 亿美元（早期可获取市场）。"
        ]
    },
    {
        "title": "商业模式",
        "content": [
            "企业许可证 / 年度订阅。",
            "POC 与付费试点。",
            "专业服务与集成服务。",
            "战略合作与行业解决方案。"
        ]
    },
    {
        "title": "当前优势",
        "content": [
            "支持 Markdown 规格输入与端到端验证流水线。",
            "自动生成 UVM、测试、断言、报告。",
            "支持 CLI 与 Web API、审计与数据持久化。",
            "提供 quick_check 与 full_verification 两种模式。"
        ]
    },
    {
        "title": "近期期望进展",
        "content": [
            "3 个月：完成企业级 MVP、1-2 个付费试点、可演示的签核证据包。",
            "6 个月：建立可复制落地模板，形成商业化路径。",
            "12 个月：实现 ARR、构建客户案例、准备 Seed/Pre-A 融资。"
        ]
    },
    {
        "title": "融资与下一步",
        "content": [
            "推荐阶段：Pre-seed / Seed。",
            "目标融资：80–300 万美元（若为概念阶段），Seed 时 500–1500 万美元。",
            "核心信息：解决真实企业痛点，边界清晰，价值在于可复现可审计。"
        ]
    }
]

prs = Presentation()
blank_slide_layout = prs.slide_layouts[5]

for i, slide_data in enumerate(slides):
    if i == 0:
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        title = slide.shapes.title
        subtitle = slide.placeholders[1]
        title.text = slide_data["title"]
        subtitle.text = "可复现、可审计、可治理的芯片验证签核平台"
    else:
        slide = prs.slides.add_slide(blank_slide_layout)
        title_shape = slide.shapes.title
        if not title_shape:
            title_shape = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(9), Inches(1))
        title_shape.text = slide_data["title"]
        title_shape.text_frame.paragraphs[0].font.size = Pt(32)

        body = slide.shapes.add_textbox(Inches(0.5), Inches(1.2), Inches(9), Inches(5.5))
        tf = body.text_frame
        tf.word_wrap = True
        for j, line in enumerate(slide_data["content"]):
            if j == 0:
                p = tf.paragraphs[0]
            else:
                p = tf.add_paragraph()
            p.text = line
            p.level = 0
            p.font.size = Pt(24)
            p.font.name = 'Arial'

prs.save('d:/SignOffAI/SignOffAI_Pitch_Deck.pptx')
print('Created SignOffAI_Pitch_Deck.pptx')
