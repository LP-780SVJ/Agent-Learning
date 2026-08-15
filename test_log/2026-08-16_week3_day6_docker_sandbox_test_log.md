# Week3 Day6 Docker Sandbox 测试验收日志

日期：2026-08-16  
目标分支：week3  
任务开始时目标 HEAD：49b0b6de2df636bb3c7f371f520f8af55c6612c7  
被测能力层：Workspace & Sandbox / Tool Runtime / Agent Runtime Safe Execution  
主要证明能力：通过 Docker backend 对不可信 Coding Agent 命令施加文件系统、网络、资源、capability 和 mount 边界。

## 1. 本次新增或修改的测试文件

- 修改：`tests/sandbox/test_docker_builder.py`
  - 新增 `test_builder_returns_argv_tuple_not_shell_string`
  - 新增 `/var` 敏感 host path 拒绝断言
  - 新增 `test_docker_runner_delegates_structured_docker_argv_to_command_runner`
- 新增：`test_log/2026-08-16_week3_day6_docker_sandbox_test_log.md`

未修改生产代码、学习文档、prompt、项目配置或 fixtures。

## 2. 仓库与实现检查

当前工作区状态显示：

- `learning-plan/week3/day6.md` 为 staged 新增文件。
- `codeteam/sandbox/` 为未跟踪生产实现目录。
- `tests/sandbox/` 为未跟踪测试目录，本轮只在该目录内补充测试。

重要差异：

- `day6.md` 的“当前仓库检查”段落写明当时没有 `codeteam/sandbox/` 和 `tests/sandbox/`，该状态描述已过期；本次验收以当前工作区实际代码为准。
- Day6 生产实现尚未进入 `week3` 分支历史，独立 worktree 基于 `week3` HEAD 时不会自然包含 `codeteam/sandbox/`，这会阻塞安全合并收尾。

## 3. Day6 验收要求覆盖矩阵

| 要求 | 覆盖测试 | 结果 |
| --- | --- | --- |
| docker run argv 是 list/tuple，不是 shell string | `test_builder_returns_argv_tuple_not_shell_string` | PASS |
| DockerRunner 交给命令执行层的是结构化 argv | `test_docker_runner_delegates_structured_docker_argv_to_command_runner` | PASS |
| 默认 `--network none` | `test_default_profile_builds_hardened_docker_run_argv` | PASS |
| 默认 `--read-only` | `test_default_profile_builds_hardened_docker_run_argv` | PASS |
| 默认 `--pull=never` | `test_default_profile_builds_hardened_docker_run_argv` | PASS |
| 默认 `--cap-drop ALL` | `test_default_profile_builds_hardened_docker_run_argv` | PASS |
| 默认 `--security-opt no-new-privileges` | `test_default_profile_builds_hardened_docker_run_argv` | PASS |
| 默认 memory / cpu / pids limit | `test_default_profile_builds_hardened_docker_run_argv` | PASS |
| 只允许 workspace bind mount 到 `/workspace` | `test_builder_outputs_exactly_one_workspace_bind_mount` | PASS |
| `workspace_write=False` 时 mount read-only | `test_workspace_write_false_makes_workspace_mount_read_only` | PASS |
| 禁止 Docker socket mount | `test_workspace_mount_source_rejects_forbidden_host_paths[/var/run/docker.sock]` | PASS |
| 禁止 `/`、`/etc`、`/usr` | `test_workspace_mount_source_rejects_forbidden_host_paths` | PASS |
| 禁止 `/var` | `test_workspace_mount_source_rejects_forbidden_host_paths[/var]` | FAIL |
| 禁止 `.ssh`、`.env`、`.aws`、`.kube` credential marker | `test_workspace_mount_source_rejects_credential_markers` | PASS |
| `cwd` 不能 escape workspace | `test_context_rejects_cwd_outside_workspace` | PASS |
| Docker mount source 不应把 `/tmp/...` 改写为 `/private/tmp/...` | `test_workspace_mount_preserves_docker_visible_tmp_alias` | PASS |

## 4. Docker integration 覆盖

已有 integration 测试：

- `test_read_workspace_succeeds_when_docker_available`
- `test_write_workspace_succeeds_when_docker_available`
- `test_unmounted_host_secret_is_not_readable_when_docker_available`
- `test_network_is_blocked_when_docker_available`
- `test_root_filesystem_write_fails_but_workspace_write_succeeds`
- `test_docker_socket_is_not_mounted_when_docker_available`

本环境执行结果：全部 conditional skip。

skip 原因：

```text
Docker CLI/daemon is unavailable; boundary tests not run:
permission denied while trying to connect to the docker API at
unix:///Users/sqlee/.colima/default/docker.sock
```

单独探测：

```text
docker version
exit code: 1
Client: Docker Engine - Community 29.7.2
Context: colima
permission denied while trying to connect to the docker API at unix:///Users/sqlee/.colima/default/docker.sock
```

未真实验证范围：

- 容器内读 `/workspace` 成功
- 容器内写 `/workspace` 成功
- 容器内读未挂载 host secret 失败
- 默认网络访问失败
- root filesystem 写入失败
- Docker socket 不存在或不可访问
- Docker inspect 的实际 HostConfig / Mounts / NetworkMode / ReadonlyRootfs
- pids limit 行为
- timeout cleanup / container leak

这些不能记为通过，需要由可访问 Docker daemon 且本地已有 `codeteam-sandbox:latest` 镜像的主终端复跑。

## 5. 实际执行命令与结果摘要

### 5.1 Builder 单测

```bash
.venv/bin/python -m pytest tests/sandbox/test_docker_builder.py -q
```

结果：

```text
exit code: 1
21 passed, 1 failed
失败：test_workspace_mount_source_rejects_forbidden_host_paths[/var]
```

### 5.2 Sandbox 测试目录

```bash
.venv/bin/python -m pytest tests/sandbox -q -rs
```

结果：

```text
exit code: 1
21 passed, 1 failed, 6 skipped
失败：test_workspace_mount_source_rejects_forbidden_host_paths[/var]
skip：6 个 Docker integration，原因均为 Docker daemon permission denied
```

### 5.3 Ruff

```bash
.venv/bin/python -m ruff check codeteam/sandbox tests/sandbox
```

结果：

```text
exit code: 0
All checks passed!
```

### 5.4 Mypy

```bash
.venv/bin/python -m mypy codeteam/sandbox tests/sandbox
```

结果：

```text
exit code: 0
Success: no issues found in 8 source files
```

### 5.5 全量 pytest

```bash
.venv/bin/python -m pytest -q
```

结果：

```text
exit code: 1
642 passed, 1 failed, 6 skipped
失败：test_workspace_mount_source_rejects_forbidden_host_paths[/var]
skip：6 个 Docker integration，原因均为 Docker daemon permission denied
```

## 6. 失败测试及原因分类

### P1 SECURITY_FAILURE / PRODUCTION_DEFECT：`/var` host path 未被拒绝

模块：`codeteam/sandbox/docker_builder.py`

测试：

```text
tests/sandbox/test_docker_builder.py::test_workspace_mount_source_rejects_forbidden_host_paths[/var]
```

复现命令：

```bash
.venv/bin/python -m pytest tests/sandbox/test_docker_builder.py -q
```

预期结果：

```text
DockerCommandBuilder.build() 对 workspace_root=/var 抛出 SandboxMountError。
```

实际结果：

```text
Failed: DID NOT RAISE SandboxMountError
```

初步原因：

```text
FORBIDDEN_HOST_PATHS 当前包含 "/", "/etc", "/usr", "/var/run/docker.sock"，
但没有直接包含 "/var"。因此 "/var" 本身会通过 mount source 校验。
```

影响：

```text
违反 Day6 mount security 要求“禁止 /、/etc、/var、/usr 等敏感 host path”。
如果上层错误地把 workspace_root 配为 /var，builder 不会 fail closed。
```

当前处理：

```text
保留失败测试；未修改生产代码；未 skip/xfail；未降低断言。
```

## 7. 已确认的生产代码缺陷

- P1：`DockerCommandBuilder` 未拒绝 `/var` 作为 workspace bind mount source。

未确认但需要后续真实 Docker 环境验证：

- Docker inspect 实际配置是否与 argv 一致。
- pids limit 是否真实生效。
- timeout 后容器是否清理。
- Docker Desktop / Colima bind mount 可见性和 I/O 性能。

## 8. 未覆盖或无法验证内容

未覆盖：

- Docker inspect 验证 `ReadonlyRootfs`、`HostConfig.Memory`、`NanoCpus`、`PidsLimit`、`CapDrop`、`SecurityOpt`、`NetworkMode`、`Mounts`。
- pids limit 行为测试。
- timeout cleanup / container leak 测试。
- benchmark：startup overhead、command overhead、workspace I/O、cleanup。
- ablation：关闭 network none、read-only root、cap-drop、pids limit、main mount baseline 的对照结果。

无法验证：

- 真实 Docker boundary tests，因为当前终端无法访问 Colima Docker socket。

## 9. Step 7 最终结论

Step 7：部分通过 / BLOCKED by environment。

理由：

- Builder / mount security 单测可运行，并发现 1 个真实安全缺陷。
- Docker integration 测试具备 conditional skip 机制和覆盖目标，但本环境因 Docker daemon permission denied 未实际执行。
- 因 `/var` mount 拒绝失败，mount security 不能判定通过。

## 10. Day6 总体结论

功能验收：部分通过

- `SandboxProfile`、`SandboxExecutionContext`、`DockerCommandBuilder`、`DockerRunner` 最小闭环存在。
- DockerRunner 结构化转交 argv 的测试通过。
- 真实容器执行未验证。

安全验收：未通过

- 默认无网络、read-only root、pull never、cap-drop、no-new-privileges、资源限制、单 workspace mount 的 builder 证据通过。
- `/var` host path 未被拒绝，违反 mount security hard invariant。
- 真实 Docker runtime 边界因环境阻塞未验证。

Benchmark：未完成

- 本轮未执行 startup / I/O / cleanup / resource behavior benchmark。

Ablation：未完成

- 本轮未执行 network/read-only/cap/pids/shared mount ablation。

Failure cases：部分完成

- 已记录 Docker socket exposure、implicit pull、read-only root、UID/GID、container leak、Docker Desktop/Colima I/O 等后续关注项。
- 已新增并确认 `/var` sensitive host path 未拒绝的 failure case。

总体结论：部分通过，但 Day6 安全验收未通过；真实 Docker integration 为环境阻塞。

## 11. 后续需要 coder 或主终端完成的事项

1. Coder 修复生产代码：将 `/var` 纳入 forbidden host path，并保持 `/var/run/docker.sock` 等更具体路径拒绝。
2. 将 Day6 生产实现纳入目标分支历史；当前 `codeteam/sandbox/` 仍是未跟踪文件，测试提交不能单独安全合并。
3. 在可访问 Docker daemon 的主 Codex 终端或用户本机终端复跑：

```bash
.venv/bin/python -m pytest tests/sandbox -q -rs
```

4. 补充 Docker inspect、pids limit、timeout cleanup / container leak 的正式 integration 测试。
5. 后续再执行 Day6 benchmark 和 ablation，当前没有足够证据支持性能或设计贡献结论。

## 12. P1 修复后复验

复验时间：2026-08-16  
复验环境：主 Codex 终端，可访问 Colima Docker daemon  

生产修复范围：

- `codeteam/sandbox/docker_builder.py`

测试更新范围：

- `tests/sandbox/test_docker_builder.py`

修复摘要：

- 将 forbidden host path 分成精确危险根路径和递归危险子树。
- 精确拒绝 `/`、`/var`、`/private/var`。
- 递归拒绝 `/etc`、`/usr`、`/var/run/docker.sock` 以及 `/var/lib`、`/var/db`、`/var/root`、`/var/log`、`/var/backups` 等敏感子树。
- 保留 macOS 临时目录例外，不误拒绝 `/private/var/folders/...` 和 `/var/folders/...`。
- 保留 Docker mount source alias，不把 `/tmp/...` 改写成 Docker daemon 不可见的 `/private/tmp/...`。

新增回归覆盖：

- `/etc/project` 必须拒绝。
- `/usr/local/project` 必须拒绝。
- `/var/lib/project`、`/var/db/project`、`/var/root/project` 等敏感子树必须拒绝。
- `/private/var/folders/.../workspace` 必须允许。
- `/var/folders/.../workspace` 必须允许。

复验命令与结果：

```bash
.venv/bin/python -m pytest tests/sandbox/test_docker_builder.py -q
```

```text
36 passed in 0.09s
```

```bash
.venv/bin/python -m pytest tests/sandbox -q -rs
```

```text
42 passed in 1.97s
```

```bash
.venv/bin/python -m ruff check codeteam/sandbox tests/sandbox
```

```text
All checks passed!
```

```bash
.venv/bin/python -m mypy codeteam/sandbox tests/sandbox
```

```text
Success: no issues found in 8 source files
```

```bash
.venv/bin/python -m pytest -q
```

```text
663 passed in 10.50s
```

更新后结论：

- Day6 功能验收：通过。
- Day6 builder / mount security：通过。
- Day6 Step 7 Docker boundary integration：通过；本次在可访问 Docker daemon 的主终端真实执行，无 skip。
- Day6 benchmark / ablation：按当前学习规则延后到 Week3 周级收尾统一执行。
- 剩余后续项：Docker inspect、pids limit、timeout cleanup / container leak 可以作为 Week3 周级 hardening 或 Day7 之后补强项。
