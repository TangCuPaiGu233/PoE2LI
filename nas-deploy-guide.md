## NAS Docker 通用部署指南

### 连接信息

| 项目 | 值 |
|------|------|
| NAS IP | 192.168.110.26 |
| SSH 端口 | 2212 |
| 用户 | skc |
| Docker 路径 | /usr/local/bin/docker |

```bash
ssh -p 2212 skc@192.168.110.26
```

### 部署步骤

**1. 把项目传到 NAS**

NAS 上创建项目目录，推荐放在 `/volume1/docker/` 下：

```bash
mkdir -p /volume1/docker/你的项目名
```

本地通过 Git 克隆或 SCP 传输代码上去。如果项目有 GitHub 仓库，直接在 NAS 上 clone 最方便：

```bash
cd /volume1/docker/你的项目名
git clone git@github.com:xxx/xxx.git .
```

**2. 准备环境变量**

如果项目有 `.env.example`，复制一份为 `.env` 并填写实际值：

```bash
cp .env.example .env
vi .env   # 或用其他编辑器
```

**3. 构建并启动**

注意 docker 要用完整路径：

```bash
cd /volume1/docker/你的项目名
/usr/local/bin/docker compose up -d --build
```

首次构建比较慢，后续有缓存会快很多。如果 pip install 超时，在 Dockerfile 里加清华镜像源：

```dockerfile
RUN pip install -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn -r requirements.txt
```

**4. 确认运行状态**

```bash
/usr/local/bin/docker compose ps
/usr/local/bin/docker compose logs -f --tail=50
```

**5. 更新项目**

```bash
cd /volume1/docker/你的项目名
git pull
/usr/local/bin/docker compose up -d --build
```

### 常用命令速查

```bash
# 查看所有容器
/usr/local/bin/docker ps

# 查看某个项目的容器
cd /volume1/docker/项目名 && /usr/local/bin/docker compose ps

# 查看日志
/usr/local/bin/docker compose logs -f 服务名

# 重启单个服务
/usr/local/bin/docker compose restart 服务名

# 停止项目
/usr/local/bin/docker compose down

# 停止并清除所有数据（慎用）
/usr/local/bin/docker compose down --rmi all --volumes

# 清理悬空镜像释放空间
/usr/local/bin/docker image prune -f

# 进入容器调试
/usr/local/bin/docker exec -it 容器名 bash
```

### 注意事项

- skc 用户 PATH 里没有 docker，所有命令都要用 `/usr/local/bin/docker` 完整路径，或者先执行 `export PATH="/usr/local/bin:$PATH"`
- NAS 的 crontab 不可用，如果需要定时任务可以用轮询守护进程替代
- NAS 重启后所有容器如果设置了 `restart: unless-stopped` 会自动恢复，否则需要手动 `docker compose up -d`
- 磁盘空间不够时清理旧镜像：`/usr/local/bin/docker image prune -a`
