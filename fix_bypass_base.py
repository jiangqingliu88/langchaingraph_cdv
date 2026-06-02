filepath = 'src/core/base.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 在 execute_task 方法开头添加 bypass 检查
old = '''async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        start_time = datetime.now()
        self.status = AgentStatus.BUSY
        await self.notify_start(self.role, task)
        try:
            processed_input = await self._pre_process(task)
            if self._executor:
                result = await self._executor.ainvoke({"input": processed_input})
            else:
                result = await self._execute(processed_input)'''

new = '''async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        bypass = task.get('bypass', self.config.get('bypass', False))
        start_time = datetime.now()
        self.status = AgentStatus.BUSY
        await self.notify_start(self.role, task)
        try:
            processed_input = await self._pre_process(task)
            if bypass:
                result = {"output": f"[{self.display_name}] bypass mode"}
            elif self._executor:
                result = await self._executor.ainvoke({"input": processed_input})
            else:
                result = await self._execute(processed_input)'''

content = content.replace(old, new)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
