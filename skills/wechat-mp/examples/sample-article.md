---
title: 别再手写 CRUD 了：一个接口层抽象，砍掉 60% 重复代码
title_short: 一个抽象砍掉 60% 重复代码
summary: 把鉴权、日志、响应包装、异常兜底从每个接口里抽走，单个查询接口从 35 行降到 10 行，以及我们踩过的三个坑。
author: 云光迷途
tag: 技术拆解
theme: tech
---

# 别再手写 CRUD 了：一个接口层抽象，砍掉 60% 重复代码

上周帮同事 review 一个后台项目，`user` 模块 8 个接口、`order` 模块 11 个接口，每一个都在重复同一套东西：校验参数、拼查询条件、判空、转 DTO、包一层统一响应。

**光看代码就知道，这项目再堆三个模块就要失控。**

这篇聊聊我们怎么用一个薄薄的抽象把这层重复砍掉，以及我们踩过的三个坑。

> [!NOTE] 本文前提
> 项目用的是 Spring Boot + MyBatis-Plus，但不依赖具体框架，思路对 Go / Node 同样成立。

## 重复到底重复在哪

把所有接口摊开看，真正变化的部分其实只有三处：

| 变化点 | 说明 | 能否抽走 |
|---|---|---|
| 查询条件拼装 | 每个模块的筛选项不同 | 否，保留 |
| 参数校验规则 | 字段和规则不同 | 否，保留 |
| 周边流程 | 鉴权、日志、响应包装、异常兜底 | **能，全部抽走** |

所以抽象的目标不是"消灭样板代码"，而是**把不变的流程钉死，把变化的部分留在原地**。

### 一个典型的坏抽象长什么样

很多人第一反应是搞个 `BaseService<T>`，然后让所有 Service 继承它：

```java
public abstract class BaseService<T> {
    protected abstract T doQuery(Map<String, Object> params);

    public Result<List<T>> query(Map<String, Object> params) {
        // 校验、日志、异常、包装……
        T data = doQuery(params);
        return Result.ok(data);
    }
}
```

看起来很美，但这里埋了两个雷：

1. `Map<String, Object> params` 把类型信息全丢了，IDE 补全和编译期检查一起消失
2. 抽象方法一多，子类就得实现一堆自己根本用不上的东西

> 抽象的代价从来不是写出来那一瞬间，而是半年后新人接手时的理解成本。

## 我们最后用的做法

核心只有一句话：**用泛型把类型留住，用组合把流程拆开。**

### 第一层：请求对象自己带校验

与其在 Service 里 `if (xxx == null) throw`，不如让请求对象自己负责：

```java
public record UserQuery(
    @Max(100) Integer pageSize,
    String keyword,
    @DateTimeFormat(pattern = "yyyy-MM-dd") LocalDate since
) {}
```

配合 Spring 的 `@Valid`，校验逻辑从「每个接口手写」变成「框架统一执行」。

### 第二层：查询条件用 Builder 收口

```java
public class UserQueryBuilder {
    public static LambdaQueryWrapper<User> build(UserQuery q) {
        return Wrappers.<User>lambdaQuery()
            .like(StringUtils.hasText(q.keyword()), User::getName, q.keyword())
            .ge(q.since() != null, User::getCreatedAt, q.since());
    }
}
```

关键是 `like` 的第一个参数是布尔条件——**条件为 false 时该 where 子句自动跳过**，不用再写 if。

### 第三层：切面处理周边流程

鉴权、耗时日志、异常兜底、统一响应，全部交给 `@RestControllerAdvice` 和自定义拦截器，业务代码里一行都看不到。

## 收益与代价

改造前后对比：

| 指标 | 改造前 | 改造后 |
|---|---|---|
| 单个查询接口代码行数 | 35 ~ 50 行 | 8 ~ 12 行 |
| 新增模块接入耗时 | 半天 | 约 1 小时 |
| 异常兜底覆盖率 | 约 40% | 100% |

代价也很实在：**团队的 Debug 路径变长了**。新人遇到问题，不是看 Service 就能定位，得知道切面在哪。

所以我们补了两件事：

- 在 `README` 里画了一张请求流转图，标清哪一步去哪找
- 所有切面统一用 `@Order` 编号，名字里带上职责

> [!WARNING] 别在项目中期动这层
> 如果你的项目已经有 30 个以上接口，改造的收益大概率覆盖不了回归测试的成本。留到下一次大版本重构。

## 三个真实的坑

1. **泛型擦除导致规则拿不到**：我们一开始用 `Class<T>` 反射拿泛型，结果在嵌套泛型上翻车，最后改成显式传一个 `TypeReference`。
2. **Builder 里的条件判断顺序**：`like` 和 `orderBy` 混用时，如果在 `orderBy` 之后再追加 where，MyBatis-Plus 生成的 SQL 会错位。**先拼条件，最后排序。**
3. **统一响应包装把分页吞了**：`Result.ok(data)` 里 data 是 `Page` 对象，前端拿不到 total。后来在包装层对 `IPage` 做了特判。

---

写完回头看，这套东西的价值不在代码量，而在于**让下一次加接口变成一件无聊的事**。无聊，往往就是工程化该有的样子。

如果你们团队也在处理类似问题，欢迎留言说说踩过的坑。
