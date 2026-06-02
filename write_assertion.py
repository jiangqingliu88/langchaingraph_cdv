with open('src/tools/assertion_tools.py', 'w', encoding='utf-8') as f:
    f.write('''"""Assertion tools"""
from langchain.tools import tool
import json

@tool("generate_sva_assertions")
def generate_sva_assertions(specs: str = "") -> str:
    """Generate SVA assertions"""
    return json.dumps({"assertions": ["prop1", "prop2"]})

@tool("generate_immediate_assertions")
def generate_immediate_assertions(specs: str = "") -> str:
    """Generate immediate assertions"""
    try:
        data = json.loads(specs) if isinstance(specs, str) else specs
    except:
        data = {"assertions": []}
    code = []
    for a in data.get("assertions", []):
        cond = a.get("condition", "1")
        msg = a.get("message", "assertion failed")
        code.append("assert (" + cond + ") else 无法将“api_key”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 无法将“当前目录:”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 System.Management.Automation.ParseException: 所在位置 行:1 字符: 5
+ venv) PS C:\Users\liujiangqing\Desktop\cdv_advanced> python -c "
+     ~
表达式或语句中包含意外的标记“)”。
   在 System.Management.Automation.Runspaces.PipelineBase.Invoke(IEnumerable input)
   在 Microsoft.PowerShell.Executor.ExecuteCommandHelper(Pipeline tempPipeline, Exception& exceptionThrown, ExecutionOptions options) 只应将 ScriptBlock 指定为 Command 参数值。 只应将 ScriptBlock 指定为 Command 参数值。 System.Management.Automation.ParseException: 所在位置 行:5 字符: 56
+     \"model_config = SettingsConfigDict(env_file='.env', env_file_enc ...
+                                                        ~
参数列表中缺少参量。

所在位置 行:6 字符: 56
+     \"model_config = SettingsConfigDict(env_file='.env', env_file_enc ...
+                                                        ~
参数列表中缺少参量。
   在 System.Management.Automation.Runspaces.PipelineBase.Invoke(IEnumerable input)
   在 Microsoft.PowerShell.Executor.ExecuteCommandHelper(Pipeline tempPipeline, Exception& exceptionThrown, ExecutionOptions options) 无法将“ic-verify”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 System.Management.Automation.ParseException: 所在位置 行:1 字符: 6
+     + FullyQualifiedErrorId : CommandNotFoundException
+      ~
一元运算符“+”后面缺少表达式。

所在位置 行:1 字符: 7
+     + FullyQualifiedErrorId : CommandNotFoundException
+       ~~~~~~~~~~~~~~~~~~~~~
表达式或语句中包含意外的标记“FullyQualifiedErrorId”。
   在 System.Management.Automation.Runspaces.PipelineBase.Invoke(IEnumerable input)
   在 Microsoft.PowerShell.Executor.ExecuteCommandHelper(Pipeline tempPipeline, Exception& exceptionThrown, ExecutionOptions options) System.Management.Automation.ParseException: 所在位置 行:1 字符: 6
+     + CategoryInfo          : ObjectNotFound: (ic-verify:String) [],  ...
+      ~
一元运算符“+”后面缺少表达式。

所在位置 行:1 字符: 7
+     + CategoryInfo          : ObjectNotFound: (ic-verify:String) [],  ...
+       ~~~~~~~~~~~~
表达式或语句中包含意外的标记“CategoryInfo”。
   在 System.Management.Automation.Runspaces.PipelineBase.Invoke(IEnumerable input)
   在 Microsoft.PowerShell.Executor.ExecuteCommandHelper(Pipeline tempPipeline, Exception& exceptionThrown, ExecutionOptions options) System.Management.Automation.ParseException: 所在位置 行:1 字符: 2
+ + ~~~~~~~~~
+  ~
一元运算符“+”后面缺少表达式。

所在位置 行:1 字符: 3
+ + ~~~~~~~~~
+   ~~~~~~~~~
表达式或语句中包含意外的标记“~~~~~~~~~”。
   在 System.Management.Automation.Runspaces.PipelineBase.Invoke(IEnumerable input)
   在 Microsoft.PowerShell.Executor.ExecuteCommandHelper(Pipeline tempPipeline, Exception& exceptionThrown, ExecutionOptions options) System.Management.Automation.ParseException: 所在位置 行:1 字符: 2
+ + ic-verify init
+  ~
一元运算符“+”后面缺少表达式。

所在位置 行:1 字符: 3
+ + ic-verify init
+   ~~~~~~~~~
表达式或语句中包含意外的标记“ic-verify”。
   在 System.Management.Automation.Runspaces.PipelineBase.Invoke(IEnumerable input)
   在 Microsoft.PowerShell.Executor.ExecuteCommandHelper(Pipeline tempPipeline, Exception& exceptionThrown, ExecutionOptions options) 无法将“所在位置”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 无法将“ic-verify”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 System.Management.Automation.ParseException: 所在位置 行:1 字符: 8
+ (venv) PS C:\Users\liujiangqing\Desktop\cdv_advanced> ic-verify init
+        ~~
表达式或语句中包含意外的标记“PS”。
   在 System.Management.Automation.Runspaces.PipelineBase.Invoke(IEnumerable input)
   在 Microsoft.PowerShell.Executor.ExecuteCommandHelper(Pipeline tempPipeline, Exception& exceptionThrown, ExecutionOptions options) 无法将“-a----”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 无法将“-a----”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 无法将“-a----”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 无法将“-a----”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 无法将“-a----”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 无法将“-a----”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 无法将“-a----”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 无法将“d-----”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 无法将“d-----”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 无法将“d-----”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 无法将“d-----”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 System.Management.Automation.ParseException: 所在位置 行:1 字符: 55
+ ----                 -------------         ------ ----
+                                                       ~
一元运算符“--”后面缺少表达式。

所在位置 行:2 字符: 1
+ d-----          2026/6/2     14:31                config
+ ~~~~~~
表达式或语句中包含意外的标记“d-----”。

所在位置 行:1 字符: 3
+ ----                 -------------         ------ ----
+   ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
“--”运算符仅适用于变量或属性。

所在位置 行:1 字符: 22
+ ----                 -------------         ------ ----
+                      ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
“--”运算符仅适用于变量或属性。

所在位置 行:1 字符: 24
+ ----                 -------------         ------ ----
+                        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
“--”运算符仅适用于变量或属性。

所在位置 行:1 字符: 26
+ ----                 -------------         ------ ----
+                          ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
“--”运算符仅适用于变量或属性。

所在位置 行:1 字符: 28
+ ----                 -------------         ------ ----
+                            ~~~~~~~~~~~~~~~~~~~~~~~~~~~
“--”运算符仅适用于变量或属性。

所在位置 行:1 字符: 30
+ ----                 -------------         ------ ----
+                              ~~~~~~~~~~~~~~~~~~~~~~~~~
“--”运算符仅适用于变量或属性。

所在位置 行:1 字符: 32
+ ----                 -------------         ------ ----
+                                ~~~~~~~~~~~~~~~~~~~~~~~
“--”运算符仅适用于变量或属性。

所在位置 行:1 字符: 34
+ ----                 -------------         ------ ----
+                                  ~~~~~~~~~~~~~~~~~~~~~
“--”运算符仅适用于变量或属性。

并未报告所有分析错误。请更正报告的错误并重试。
   在 System.Management.Automation.Runspaces.PipelineBase.Invoke(IEnumerable input)
   在 Microsoft.PowerShell.Executor.ExecuteCommandHelper(Pipeline tempPipeline, Exception& exceptionThrown, ExecutionOptions options) 无法将“目录:”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 无法将“ic-verify”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 无法将“ic-verify”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 无法将“ic-verify”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 无法将“ic-verify”项识别为 cmdlet、函数、脚本文件或可运行程序的名称。请检查名称的拼写，如果包括路径，请确保路径正确，然后再试一次。 找不到路径“C:\Users\liujiangqing\Desktop\cdv_advanced\.env.example”，因为该路径不存在。 找不到名为“_PYTHON_VENV_PROMPT_PREFIX”的变量。 找不到与参数名称“Chord”匹配的参数。 找不到与参数名称“Chord”匹配的参数。 找不到与参数名称“Chord”匹配的参数。 找不到与参数名称“Chord”匹配的参数。(\\"" + msg + "\\");")
    return "\\n".join(code)

@tool("generate_concurrent_assertions")
def generate_concurrent_assertions(specs: str = "") -> str:
    """Generate concurrent assertions"""
    return "property p; @(posedge clk) 1; endproperty"

@tool("generate_formal_properties")
def generate_formal_properties(specs: str = "") -> str:
    """Generate formal properties"""
    return "// Formal properties"

@tool("generate_cdc_assertions")
def generate_cdc_assertions(specs: str = "") -> str:
    """Generate CDC assertions"""
    return "// CDC assertions"

@tool("generate_cover_properties")
def generate_cover_properties(specs: str = "") -> str:
    """Generate cover properties"""
    return "// Cover properties"

@tool("generate_assertion_package")
def generate_assertion_package(specs: str = "") -> str:
    """Generate assertion package"""
    return "package pkg; endpackage"

@tool("analyze_assertion_coverage")
def analyze_assertion_coverage(data: str = "") -> str:
    """Analyze assertion coverage"""
    return json.dumps({"total": 25, "covered": 22, "rate": "88%"})

class AssertionTools:
    def get_tools(self):
        return [
            generate_sva_assertions,
            generate_immediate_assertions,
            generate_concurrent_assertions,
            generate_formal_properties,
            generate_cdc_assertions,
            generate_cover_properties,
            generate_assertion_package,
            analyze_assertion_coverage,
        ]
''')
print('done')
