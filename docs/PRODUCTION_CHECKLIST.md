# 生产部署检查清单

上线前逐条过一遍。**每条都有验证命令**：命令输出符合预期才往下走。
第 3 条是总闸——`app/core/config.py` 在启动期就会拒绝带占位值的配置，
它过了基本就说明 `.env` 填完了。

前置：仓库根目录有 `.env`（`cp .env.example .env` 生成的，不入库）。

---

## 1. 环境标志

`APP_ENV` 必须是 `prod`（不是 `dev`）——dev 下 mock 支付回调是开着的。

```bash
grep '^APP_ENV=' .env          # 期望：APP_ENV=prod
```

## 2. 占位值自查

`.env` 里不能残留 `REPLACE_WITH` / `CHANGE_ME` / `<user>` 这类示例值。

```bash
grep -nE 'REPLACE_WITH|CHANGE_ME|<user>|<password>|<host>|<db>' .env   # 期望：无输出
```

## 3. 启动自检（总闸）

配置层会校验 `APP_ENV`、时区、阈值、JWT 长度、验证码强度、占位值；
任一项不合格都直接拒绝启动。

```bash
cd apps/api && python -c "from app.core.config import Settings; Settings()"   # 期望：无输出、退出码 0
```

## 4. JWT 密钥

`JWT_SECRET` 至少 32 字节且是随机值（不是示例里那串）。

```bash
python -c "import pathlib;v=[l.split('=',1)[1].strip() for l in pathlib.Path('.env').read_text().splitlines() if l.startswith('JWT_SECRET=')][0];print(len(v.encode()))"   # 期望：>= 32
```

## 5. 登录短信验证码

`LOGIN_SMS_CODE` 不是占位码 `123456`、长度至少 8 位。

```bash
python -c "import pathlib;v=[l.split('=',1)[1].strip() for l in pathlib.Path('.env').read_text().splitlines() if l.startswith('LOGIN_SMS_CODE=')][0];print(len(v), v!='123456')"   # 期望：>= 8 True
```

## 6. 数据库与缓存地址

`DATABASE_URL` / `REDIS_URL` 指向生产实例，密码是真实值。

```bash
grep -E '^(DATABASE_URL|REDIS_URL)=' .env | sed 's#://[^@]*@#://***@#'   # 期望：主机名/库名是生产值，密码已被遮住
```

## 7. `.env` 不入库

`.env` 与任何密钥文件都不进 Git。

```bash
git ls-files --error-unmatch .env 2>/dev/null || echo "OK：.env 未被跟踪"
```

## 8. 数据库迁移

生产库走 alembic（测试库走 `create_all`，两条路径都要对得上）。

```bash
cd apps/api && alembic upgrade head && alembic current   # 期望：current 指向最新 revision
```

## 9. CI 密钥已配置

GitHub Actions 里跑测试用的密钥（CI 里 `APP_ENV=dev`，缺 `LOGIN_SMS_CODE` 走占位码，其余必须配齐）。

```bash
gh secret list --repo jackli0719/xgy_gemini   # 期望：DATABASE_URL / TEST_DATABASE_URL / REDIS_URL / JWT_SECRET / POSTGRES_PASSWORD 都在
```

## 10. 启动失败日志不含密钥

配置校验失败时，错误消息只点名变量名和原因，不回显值本身——
密钥原文不会进日志（`app/core/config.py` 的报错只拼字段名，不拼值）。

```bash
cd apps/api && APP_ENV=prod DATABASE_URL=postgresql+asyncpg://u:p@h:5432/d \
  JWT_SECRET=REPLACE_WITH_RANDOM_SECRET_AT_LEAST_32_BYTES_LONG LOGIN_SMS_CODE=aB3xY9zQ7mK2 \
  python -c "from app.core.config import Settings; Settings()" 2>&1 \
  | grep -c "REPLACE_WITH_RANDOM_SECRET"   # 期望：0（报错里有 "REPLACE_WITH" 标记名，但没有密钥原文）
```
