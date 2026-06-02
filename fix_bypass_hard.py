filepath = 'src/core/base.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 找到 execute_task 并修复 bypass 逻辑
old_start = 'async def execute_task(self, task: Dict[str, Any]) -> AgentResult:'
idx = content.find(old_start)
# 找到方法结束（下一个 async def）
next_def = content.find('async def ', idx + 10)
method = content[idx:next_def]

# 直接替换整个方法
new_method = '''async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        bypass = task.get('bypass', False) if isinstance(task, dict) else False
        if bypass:
            return AgentResult(success=True, data={"output": f"[{self.display_name}] bypass mode"})
        start_time = datetime.now()
        self.status = AgentStatus.BUSY
        await self.notify_start(self.role, task)
        try:
            processed_input = await self._pre_process(task)
            if self._executor:
                result = await self._executor.ainvoke({"input": processed_input})
            else:
                result = await self._execute(processed_input)
            processed_result = await self._post_process(result)
            execution_time = (datetime.now() - start_time).total_seconds()
            self.metrics["tasks_completed"] += 1
            self.metrics["total_time"] += execution_time
            agent_result = AgentResult(success=True, data=processed_result, execution_time=execution_time)
            await self.notify_complete(self.role, agent_result)
            return agent_result
        except Exception as e:
            self.metrics["tasks_failed"] += 1
            error_result = AgentResult(success=False, error=str(e))
            await self.notify_error(self.role, e)
            return error_result
        finally:
            self.status = AgentStatus.IDLE

    '''

content = content[:idx] + new_method + content[next_def:]
with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)
print('done')
