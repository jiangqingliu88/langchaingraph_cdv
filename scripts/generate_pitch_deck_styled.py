from pptx import Presentation
from pptx.enum.text import PP_PARAGRAPH_ALIGNMENT
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt
from pptx.enum.shapes import MSO_SHAPE

slides = [
    {
        "title": "SignOffAI",
        "subtitle": "可复现、可审计、可治理的数字芯片验证签核平台",
        "content": [
            "面向功能验证与签核决策的企业级产品。",
            "让验证结果不仅是代码，而是可追溯的签核证据。"
        ]
    },
    {
        "title": "痛点：验证与签核已失序",
        "content": [
            "验证流程碎片化，规格、测试、回归、覆盖、签核不连通。",
            "签核缺乏证据链，工程师决策难以复现和审计。",
            "现有 AI 工具只能生成代码，无法满足企业级治理要求。"
        ]
    },
    {
        "title": "我们的解决方案",
        "content": [
            "从规格输入到签核输出，构建端到端验证流程平台。",
            "自动生成验证计划、UVM 环境、测试、断言、回归和覆盖分析。",
            "自动输出可审计的签核证据包和审批流。"
        ]
    },
    {
        "title": "核心价值",
        "content": [
            "✅ 可复现证据链：每一步产物、日志与数据库记录可回溯。",
            "✅ 企业级签核交付：交付签核证据包而非单纯代码。",
            "✅ 治理与审计：支持 RBAC、项目隔离、审计日志和审批流。"
        ]
    },
    {
        "title": "差异化优势",
        "content": [
            "覆盖验证到签核整个闭环，而不仅是单点生成。",
            "强调企业级合规：审计、项目隔离、审批、证据包。",
            "支持 CLI 与 Web API，适用于工程团队和管理团队。"
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
            "年度订阅 / 企业许可证。",
            "POC 与付费试点服务。",
            "专业集成与定制服务。",
            "战略合作与行业解决方案。"
        ]
    },
    {
        "title": "当前优势",
        "content": [
            "支持 Markdown 规格输入与端到端验证流水线。",
            "自动生成 UVM、测试、断言、报告。",
            "支持 quick_check 与 full_verification 两种模式。",
            "支持审计与数据持久化。"
        ]
    },
    {
        "title": "里程碑",
        "content": [
            "3 个月：完成企业级 MVP，交付 1-2 个付费试点。",
            "6 个月：建立可复制落地模型，形成商业化路径。",
            "12 个月：实现 ARR，准备 Seed/Pre-A 融资。"
        ]
    },
    {
        "title": "融资建议",
        "content": [
            "推荐阶段：Pre-seed / Seed。",
            "目标融资：80–300 万美元（概念阶段）。",
            "若已有付费 POC：Seed 轮可考虑 500–1500 万美元。"
        ]
    }
]

prs = Presentation()

# Title slide
slide_layout = prs.slide_layouts[0]
slide = prs.slides.add_slide(slide_layout)
slide.shapes.title.text = slides[0]["title"]
subtitle = slide.placeholders[1]
subtitle.text = slides[0]["subtitle"]
subtitle.text_frame.paragraphs[0].font.size = Pt(24)
subtitle.text_frame.paragraphs[0].font.color.rgb = RGBColor(80, 80, 80)

# Add content slides
for data in slides[1:]:
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = data["title"]
    body = slide.shapes.placeholders[1].text_frame
    body.clear()
    for i, line in enumerate(data["content"]):
        if i == 0:
            p = body.paragraphs[0]
        else:
            p = body.add_paragraph()
        p.text = line
        p.level = 0
        p.font.size = Pt(24)
        p.font.name = 'Arial'
        if line.startswith("✅"):
            p.font.bold = True
        p.space_after = Pt(8)
    slide.shapes.title.text_frame.paragraphs[0].font.size = Pt(32)
    slide.shapes.title.text_frame.paragraphs[0].font.bold = True
    slide.shapes.title.text_frame.paragraphs[0].font.color.rgb = RGBColor(0, 51, 102)

    left = Inches(0.3)
    top = Inches(1.5)
    width = Inches(9)
    height = Inches(0.1)
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    line.fill.solid()
    line.fill.fore_color.rgb = RGBColor(0, 51, 102)
    line.line.fill.background()

prs.save('d:/SignOffAI/SignOffAI_Pitch_Deck_Styled.pptx')
print('Created SignOffAI_Pitch_Deck_Styled.pptx')
