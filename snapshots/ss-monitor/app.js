
        // ===== i18n 引擎 =====
        // 默认 zh-Hant. 简体 = OpenCC s2t 的反向 (繁→简) 由前端字典查; 英文独立字典.
        // 元素加 data-i18n="key" → applyI18n 时替换 textContent
        // 元素加 data-i18n-placeholder="key" / data-i18n-title="key" → 替换属性
        // JS 渲染用 t('key') 读字典
        const I18N = {
            'zh-Hant': {
                // 通用
                'header.live': '咯咯',
                'header.subtitle': '養殖數據 · 24h 直播',
                // hero
                'hero.ss': '雞霸王', 'hero.vps': '雞舍', 'hero.pool': '蛋池', 'hero.feed': '飼料廠',
                'hero.checking': '檢測中...',
                // 雞霸王三態 (running+有連接=活著 / running 無連接=無人理 / 不 running=救救我)
                'ss.state.alive': '活著',
                'ss.state.lonely': '無人理',
                'ss.state.help': '救救我',
                // VPS 卡
                'vps.title': '雞舍狀態', 'vps.section.resources': '資源使用', 'vps.section.network': '網路',
                'vps.cpu': 'CPU 使用率', 'vps.mem': '記憶體', 'vps.swap': 'Swap', 'vps.disk': '磁碟',
                'vps.load': '系統負載', 'vps.process': '進程', 'vps.os': '作業系統', 'vps.kernel': '內核',
                'vps.arch': '架構', 'vps.uptime': '開機時長',
                // 蛋池卡
                'pool.title': '蛋池',
                'pool.nextCheck': '下次檢查',
                'pool.serviceStatus': '服務狀態', 'pool.uptime': '運行時長', 'pool.memory': '記憶體佔用',
                'pool.section.progress': '📊 增量探活 (30min)',
                'pool.section.stats': '🌐 狀態分布',
                'pool.section.db': '📚 訂閱源評分庫',
                'pool.section.history': '📈 探活趨勢 (最近 20 輪)',
                'pool.section.diff': '🔄 上輪 vs 這輪 Diff',
                'pool.section.nodeTable': '📋 當前輪節點表',
                'pool.tested': '測試', 'pool.alive': '通過', 'pool.media': '失敗', 'pool.speed': '通過率',
                'pool.cnProxies': 'CN 代理', 'pool.elapsed': '耗時', 'pool.stateDecaying': '▼ decaying',
                'pool.pipeline.running': '運行中', 'pool.pipeline.idle': '待機', 'pool.pipeline.unknown': '—',
                'pool.tested.completed.eta': '✓ 已完成', 'pool.tested.completed.suffix': '下輪 {eta} 後',
                'pool.tested.completed.imminent': '即將開始', 'pool.tested.completed.fallback': '共檢測 {n} 個',
                'pool.totalNodes': '節點總數', 'pool.protocols': '狀態分布', 'pool.lastRun': '上次探活',
                'pool.dbTotal': '已知源總數', 'pool.dbStatus': '狀態分布', 'pool.dbLastSync': '上次同步',
                'pool.topSources': '🌟 TOP 5 候選源 (按評分庫通過率)',
                'pool.diffAdded': '+ 新增', 'pool.diffRemoved': '- 消失', 'pool.diffKept': '= 穩定',
                'pool.search.placeholder': '搜尋 (名稱/地區/協議)...',
                'pool.sort.qualityDesc': '質量 ↓', 'pool.sort.speedDesc': '測速 ↓',
                'pool.sort.speedAsc': '測速 ↑', 'pool.sort.appearances': '出現率 ↓',
                'pool.sort.region': '地區', 'pool.sort.type': '協議',
                'pool.limitToggle': '只炫前 100 隻',
                'pool.limitToggle.title': '限制渲染前 100 隻雞 · 大幅提升頁面響應速度',
                // 表格三檔限制 (5 → mid → all)
                'limit.moreBelow': '下面還有 {n} 行',
                'limit.expandTo': '展開到 {label}',
                'limit.collapseTo': '收起到 {label}',
                'limit.all': '全部',
                // 节点表头
                'node.col.name': '名稱', 'node.col.quality': '質量', 'node.col.protocol': '協議',
                'node.col.region': '地區', 'node.col.speed': '測速', 'node.col.appearances': '出現率',
                'node.col.consecutive': '連續', 'node.col.tls': 'TLS',
                // discover 卡
                'discover.title': '覓食',
                'discover.lastRun': '最近一次掃描',
                'discover.rulesVer': '規則版本', 'discover.totalStates': '發現源總數',
                'discover.added7d': '7天新增源', 'discover.auditCount': '30天審計事件',
                'discover.section.queue': '📊 隊列掃描狀態',
                'discover.section.recentAdded': '🌱 最近 7 天新增源',
                'discover.section.audit': '🛡️ 審計事件 (最近 20 條)',
                'discover.section.queueDetail': '📋 發現隊列詳情',
                'discover.kind.awesome': 'awesome README',
                'discover.kind.topic': 'GitHub topics',
                'discover.kind.telegram': 'Telegram 頻道', 'discover.kind.tgDisabled': '未啟用',
                'discover.kind.audit': '現有源審計', 'discover.kind.auditHint': 'score < 80 才掃',
                'discover.col.kind': '類型', 'discover.col.key': '標識',
                'discover.col.priority': '優先級', 'discover.col.priority.title': '優先級越小越早掃',
                'discover.col.lastScan': '上次掃描', 'discover.col.status': '狀態',
                'discover.col.totalAdded': '累計入庫',
                'discover.col.totalAdded.title': '累計透過 6 層過濾入庫的源數',
                'discover.note': '💡 每天 02:00 自動執行 · awesome 5/天 + topic 2/天 + audit 10/天 · 嚴格不動 sources.score/status/note · 6 層過濾 (域名白名單 / IOC / 路徑 / HTTP / 內容簽名 / 重複)',
                'discover.empty.added': '尚無新增源 · 等今晚 02:00 首次執行',
                'discover.empty.audit': '尚無審計事件',
                'discover.empty.queue': '隊列為空',
                'discover.lastRun.never': '尚未執行 (等今晚 02:00)',
                // badge / status
                'status.notScanned': '未掃', 'status.ok': 'OK',
                'status.candidate': '候選', 'status.whitelisted': '白名單',
                'status.scored': '已評分', 'status.mapped': '已映射', 'status.known': '待抓取',
                'common.refresh': '重新餵食 · 刷新所有資料',
                // section / loading
                'common.loading': '加載中...', 'common.empty': '無匹配項',
                'common.unreachable': '無法觸達', 'common.passed': '通過',
                'audit.title.suffix': '審計',
                // === 选项卡 / 表头 (Phase 2 i18n) ===
                'pool.sort.consecutive': '連續 ↓',
                'src.sort.scoreDesc': '均分 ↓', 'src.sort.scoreAsc': '均分 ↑',
                'src.sort.countDesc': '節點數 ↓', 'src.sort.lowStreak': '低分連續 ↓',
                'src.sort.maturity': '成熟度 ↓',
                'src.maturity.all': '全部成熟度', 'src.maturity.scored': '僅已評分',
                'src.maturity.mapped': '僅已映射', 'src.maturity.known': '僅待抓取',
                'src.search.placeholder': '搜尋源 URL...',
                'src.limitToggle': '只炫前 50 個源',
                'src.limitToggle.title': '限制渲染前 50 個源 · 大幅提升頁面響應速度',
                // 节点级评分卡 (qualityCard)
                'quality.title': '飼料',
                'quality.cnProxy': '🛜 CN 代理探活',
                'quality.cnProxy.totalSources': '代理源總數',
                'quality.cnProxy.available': '可用源',
                'quality.cnProxy.totalProxies': '可用代理數',
                'quality.cnProxy.lastDiscovery': '上次發現',
                'quality.cnProxy.sources': '代理源列表',
                // 源级评分卡 (srcCard)
                'src.title': '飼料廠',
                // 表头共用
                'node.col.score': '質量', 'node.col.round': '輪',
                'node.col.streak': '連', 'node.col.avgSpeed': '均速',
                'node.col.latest': '最新', 'node.col.probe': '探活',
                'src.col.url': '源 URL', 'src.col.avgScore': '均分',
                'src.col.nodeCount': '節點', 'src.col.lowStreak': '低分',
                'src.col.maturity': '成熟度', 'src.col.status': '狀態',
                'src.col.trend': '趨勢',
                'src.section.progress': '📊 大輪進度 (6h)', 'src.section.poolStats': '🌐 大輪統計',
                'src.round.tested': '測活', 'src.round.alive': '存活', 'src.round.media': '媒體通過', 'src.round.speed': '測速通過',
                'src.round.totalNodes': '可用節點', 'src.round.protocols': '協議分布', 'src.round.lastRun': '上輪跑完',
                'src.section.roundHistory': '📈 大輪趨勢 (6h)',
                'src.section.progress': '📊 大輪進度 (6h)',
                'src.section.poolStats': '🌐 大輪統計',
                'src.round.tested': '測活', 'src.round.alive': '存活',
                'src.round.media': '媒體通過', 'src.round.speed': '測速 ≥512KB/s',
                'src.round.totalNodes': '可用節點', 'src.round.protocols': '協議分布',
                'src.round.lastRun': '上輪跑完',
            },
            'zh-Hans': {
                'header.live': '咯咯',
                'header.subtitle': '养殖数据 · 24h 直播',
                'hero.ss': '鸡霸王', 'hero.vps': '鸡舍', 'hero.pool': '蛋池', 'hero.feed': '饲料厂',
                'hero.checking': '检测中...',
                // 鸡霸王三态
                'ss.state.alive': '活着',
                'ss.state.lonely': '无人理',
                'ss.state.help': '救救我',
                'vps.title': '鸡舍状态', 'vps.section.resources': '资源使用', 'vps.section.network': '网络',
                'vps.cpu': 'CPU 使用率', 'vps.mem': '内存', 'vps.swap': 'Swap', 'vps.disk': '磁盘',
                'vps.load': '系统负载', 'vps.process': '进程', 'vps.os': '操作系统', 'vps.kernel': '内核',
                'vps.arch': '架构', 'vps.uptime': '开机时长',
                'pool.title': '蛋池', 'pool.nextCheck': '下次检查',
                'pool.serviceStatus': '服务状态', 'pool.uptime': '运行时长', 'pool.memory': '内存占用',
                'pool.section.progress': '📊 增量探活 (30min)',
                'pool.section.stats': '🌐 状态分布',
                'pool.section.db': '📚 订阅源评分库',
                'pool.section.history': '📈 探活趋势 (最近 20 轮)',
                'pool.section.diff': '🔄 上轮 vs 这轮 Diff',
                'pool.section.nodeTable': '📋 当前轮节点表',
                'pool.tested': '测试', 'pool.alive': '通过', 'pool.media': '失败', 'pool.speed': '通过率',
                'pool.cnProxies': 'CN 代理', 'pool.elapsed': '耗时', 'pool.stateDecaying': '▼ decaying',
                'pool.pipeline.running': '运行中', 'pool.pipeline.idle': '待机', 'pool.pipeline.unknown': '—',
                'pool.tested.completed.eta': '✓ 已完成', 'pool.tested.completed.suffix': '下轮 {eta} 后',
                'pool.tested.completed.imminent': '即将开始', 'pool.tested.completed.fallback': '共检测 {n} 个',
                'pool.totalNodes': '节点总数', 'pool.protocols': '状态分布', 'pool.lastRun': '上次探活',
                'pool.dbTotal': '已知源总数', 'pool.dbStatus': '状态分布', 'pool.dbLastSync': '上次同步',
                'pool.topSources': '🌟 TOP 5 候选源 (按评分库通过率)',
                'pool.diffAdded': '+ 新增', 'pool.diffRemoved': '- 消失', 'pool.diffKept': '= 稳定',
                'pool.search.placeholder': '搜索 (名称/地区/协议)...',
                'pool.sort.qualityDesc': '质量 ↓', 'pool.sort.speedDesc': '测速 ↓',
                'pool.sort.speedAsc': '测速 ↑', 'pool.sort.appearances': '出现率 ↓',
                'pool.sort.region': '地区', 'pool.sort.type': '协议',
                'pool.limitToggle': '只炫前 100 只',
                'pool.limitToggle.title': '限制渲染前 100 只鸡 · 大幅提升页面响应速度',
                // 表格三档限制 (5 → mid → all)
                'limit.moreBelow': '下面还有 {n} 行',
                'limit.expandTo': '展开到 {label}',
                'limit.collapseTo': '收起到 {label}',
                'limit.all': '全部',
                'node.col.name': '名称', 'node.col.quality': '质量', 'node.col.protocol': '协议',
                'node.col.region': '地区', 'node.col.speed': '测速', 'node.col.appearances': '出现率',
                'node.col.consecutive': '连续', 'node.col.tls': 'TLS',
                'discover.title': '觅食',
                'discover.lastRun': '最近一次扫描',
                'discover.rulesVer': '规则版本', 'discover.totalStates': '发现源总数',
                'discover.added7d': '7天新增源', 'discover.auditCount': '30天审计事件',
                'discover.section.queue': '📊 队列扫描状态',
                'discover.section.recentAdded': '🌱 最近 7 天新增源',
                'discover.section.audit': '🛡️ 审计事件 (最近 20 条)',
                'discover.section.queueDetail': '📋 发现队列详情',
                'discover.kind.awesome': 'awesome README',
                'discover.kind.topic': 'GitHub topics',
                'discover.kind.telegram': 'Telegram 频道', 'discover.kind.tgDisabled': '未启用',
                'discover.kind.audit': '现有源审计', 'discover.kind.auditHint': 'score < 80 才扫',
                'discover.col.kind': '类型', 'discover.col.key': '标识',
                'discover.col.priority': '优先级', 'discover.col.priority.title': '优先级越小越早扫',
                'discover.col.lastScan': '上次扫描', 'discover.col.status': '状态',
                'discover.col.totalAdded': '累计入库',
                'discover.col.totalAdded.title': '累计透过 6 层过滤入库的源数',
                'discover.note': '💡 每天 02:00 自动执行 · awesome 5/天 + topic 2/天 + audit 10/天 · 严格不动 sources.score/status/note · 6 层过滤 (域名白名单 / IOC / 路径 / HTTP / 内容签名 / 重复)',
                'discover.empty.added': '尚无新增源 · 等今晚 02:00 首次执行',
                'discover.empty.audit': '尚无审计事件',
                'discover.empty.queue': '队列为空',
                'discover.lastRun.never': '尚未执行 (等今晚 02:00)',
                'status.notScanned': '未扫', 'status.ok': 'OK',
                'status.candidate': '候选', 'status.whitelisted': '白名单',
                'status.scored': '已评分', 'status.mapped': '已映射', 'status.known': '待抓取',
                'common.refresh': '重新喂食 · 刷新所有数据',
                'common.loading': '加载中...', 'common.empty': '无匹配项',
                'common.unreachable': '无法触达', 'common.passed': '通过',
                'audit.title.suffix': '审计',
                // === 选项卡 / 表头 (Phase 2 i18n) ===
                'pool.sort.consecutive': '连续 ↓',
                'src.sort.scoreDesc': '均分 ↓', 'src.sort.scoreAsc': '均分 ↑',
                'src.sort.countDesc': '节点数 ↓', 'src.sort.lowStreak': '低分连续 ↓',
                'src.sort.maturity': '成熟度 ↓',
                'src.maturity.all': '全部成熟度', 'src.maturity.scored': '仅已评分',
                'src.maturity.mapped': '仅已映射', 'src.maturity.known': '仅待抓取',
                'src.search.placeholder': '搜索源 URL...',
                'src.limitToggle': '只炫前 50 个源',
                'src.limitToggle.title': '限制渲染前 50 个源 · 大幅提升页面响应速度',
                'quality.title': '饲料',
                'quality.cnProxy': '🛜 CN 代理探活',
                'quality.cnProxy.totalSources': '代理源总数',
                'quality.cnProxy.available': '可用源',
                'quality.cnProxy.totalProxies': '可用代理数',
                'quality.cnProxy.lastDiscovery': '上次发现',
                'quality.cnProxy.sources': '代理源列表',
                'src.title': '饲料厂',
                'node.col.score': '质量', 'node.col.round': '轮',
                'node.col.streak': '连', 'node.col.avgSpeed': '均速',
                'node.col.latest': '最新', 'node.col.probe': '探活',
                'src.col.url': '源 URL', 'src.col.avgScore': '均分',
                'src.col.nodeCount': '节点', 'src.col.lowStreak': '低分',
                'src.col.maturity': '成熟度', 'src.col.status': '状态',
                'src.col.trend': '趋势',
                'src.section.progress': '📊 大轮进度 (6h)', 'src.section.poolStats': '🌐 大轮统计',
                'src.round.tested': '测活', 'src.round.alive': '存活', 'src.round.media': '媒体通过', 'src.round.speed': '测速通过',
                'src.round.totalNodes': '可用节点', 'src.round.protocols': '协议分布', 'src.round.lastRun': '上轮跑完',
                'src.section.roundHistory': '📈 大轮趋势 (6h)',
                'src.section.progress': '📊 大轮进度 (6h)',
                'src.section.poolStats': '🌐 大轮统计',
                'src.round.tested': '测活', 'src.round.alive': '存活',
                'src.round.media': '媒体通过', 'src.round.speed': '测速 ≥512KB/s',
                'src.round.totalNodes': '可用节点', 'src.round.protocols': '协议分布',
                'src.round.lastRun': '上轮跑完',
            },
            'en': {
                'header.live': 'LIVE',
                'header.subtitle': 'Farm Data · 24h Live',
                'hero.ss': 'Rooster King', 'hero.vps': 'Coop', 'hero.pool': 'Egg Pool', 'hero.feed': 'Feed Mill',
                'hero.checking': 'Checking...',
                // SS chicken triple state
                'ss.state.alive': 'Alive',
                'ss.state.lonely': 'Lonely',
                'ss.state.help': 'Help!',
                'vps.title': 'Coop Status', 'vps.section.resources': 'Resources', 'vps.section.network': 'Network',
                'vps.cpu': 'CPU Usage', 'vps.mem': 'Memory', 'vps.swap': 'Swap', 'vps.disk': 'Disk',
                'vps.load': 'Load Avg', 'vps.process': 'Processes', 'vps.os': 'OS', 'vps.kernel': 'Kernel',
                'vps.arch': 'Arch', 'vps.uptime': 'Uptime',
                'pool.title': 'Egg Pool', 'pool.nextCheck': 'Next Check',
                'pool.serviceStatus': 'Service', 'pool.uptime': 'Uptime', 'pool.memory': 'Memory',
                'pool.section.progress': '📊 Incremental Probe (30min)',
                'pool.section.stats': '🌐 State Distribution',
                'pool.section.db': '📚 Source Score DB',
                'pool.section.history': '📈 Probe Trend (Last 20)',
                'pool.section.diff': '🔄 Last Round vs This Round Diff',
                'pool.section.nodeTable': '📋 Current Round Nodes',
                'pool.tested': 'Tested', 'pool.alive': 'Passed', 'pool.media': 'Failed', 'pool.speed': 'Pass Rate',
                'pool.cnProxies': 'CN Proxy', 'pool.elapsed': 'Elapsed', 'pool.stateDecaying': '▼ decaying',
                'pool.pipeline.running': 'Running', 'pool.pipeline.idle': 'Idle', 'pool.pipeline.unknown': '—',
                'pool.tested.completed.eta': '✓ Done', 'pool.tested.completed.suffix': 'next in {eta}',
                'pool.tested.completed.imminent': 'starting soon', 'pool.tested.completed.fallback': '{n} checked',
                'pool.totalNodes': 'Total Nodes', 'pool.protocols': 'State Dist', 'pool.lastRun': 'Last Probe',
                'pool.dbTotal': 'Known Sources', 'pool.dbStatus': 'Status Dist', 'pool.dbLastSync': 'Last Sync',
                'pool.topSources': '🌟 TOP 5 Candidate Sources (by pass rate)',
                'pool.diffAdded': '+ Added', 'pool.diffRemoved': '- Removed', 'pool.diffKept': '= Stable',
                'pool.search.placeholder': 'Search (name/region/proto)...',
                'pool.sort.qualityDesc': 'Quality ↓', 'pool.sort.speedDesc': 'Speed ↓',
                'pool.sort.speedAsc': 'Speed ↑', 'pool.sort.appearances': 'Appearances ↓',
                'pool.sort.region': 'Region', 'pool.sort.type': 'Protocol',
                'pool.limitToggle': 'Top 100 only',
                'pool.limitToggle.title': 'Render top 100 only · faster page response',
                // Table 3-stage limit (5 → mid → all)
                'limit.moreBelow': '{n} more below',
                'limit.expandTo': 'Expand to {label}',
                'limit.collapseTo': 'Collapse to {label}',
                'limit.all': 'all',
                'node.col.name': 'Name', 'node.col.quality': 'Quality', 'node.col.protocol': 'Proto',
                'node.col.region': 'Region', 'node.col.speed': 'Speed', 'node.col.appearances': 'Appear',
                'node.col.consecutive': 'Streak', 'node.col.tls': 'TLS',
                'discover.title': 'Foraging',
                'discover.lastRun': 'Last scan',
                'discover.rulesVer': 'Rules Version', 'discover.totalStates': 'Discover Sources',
                'discover.added7d': '7d Added', 'discover.auditCount': '30d Audit Events',
                'discover.section.queue': '📊 Queue Scan Status',
                'discover.section.recentAdded': '🌱 Recent 7d Added Sources',
                'discover.section.audit': '🛡️ Audit Events (Last 20)',
                'discover.section.queueDetail': '📋 Discover Queue Detail',
                'discover.kind.awesome': 'awesome README',
                'discover.kind.topic': 'GitHub topics',
                'discover.kind.telegram': 'Telegram Channels', 'discover.kind.tgDisabled': 'Disabled',
                'discover.kind.audit': 'Existing Source Audit', 'discover.kind.auditHint': 'only scan score < 80',
                'discover.col.kind': 'Kind', 'discover.col.key': 'Key',
                'discover.col.priority': 'Priority', 'discover.col.priority.title': 'Smaller = scanned earlier',
                'discover.col.lastScan': 'Last Scan', 'discover.col.status': 'Status',
                'discover.col.totalAdded': 'Total Added',
                'discover.col.totalAdded.title': 'Total sources passing 6-layer filter and inserted',
                'discover.note': '💡 Runs daily at 02:00 · awesome 5/day + topic 2/day + audit 10/day · Strictly does NOT touch sources.score/status/note · 6-layer filter (domain whitelist / IOC / path / HTTP / content signature / dedup)',
                'discover.empty.added': 'No new sources yet · waiting for tonight 02:00',
                'discover.empty.audit': 'No audit events',
                'discover.empty.queue': 'Queue empty',
                'discover.lastRun.never': 'Not run yet (waiting tonight 02:00)',
                'status.notScanned': 'Pending', 'status.ok': 'OK',
                'status.candidate': 'Candidate', 'status.whitelisted': 'Whitelist',
                'status.scored': 'Scored', 'status.mapped': 'Mapped', 'status.known': 'Pending Fetch',
                'common.refresh': 'Feed again · Refresh all data',
                'common.loading': 'Loading...', 'common.empty': 'No matches',
                'common.unreachable': 'Unreachable', 'common.passed': 'Passed',
                'audit.title.suffix': 'Audit',
                'pool.sort.consecutive': 'Streak ↓',
                'src.sort.scoreDesc': 'Avg Score ↓', 'src.sort.scoreAsc': 'Avg Score ↑',
                'src.sort.countDesc': 'Node Count ↓', 'src.sort.lowStreak': 'Low Streak ↓',
                'src.sort.maturity': 'Maturity ↓',
                'src.maturity.all': 'All Maturity', 'src.maturity.scored': 'Scored Only',
                'src.maturity.mapped': 'Mapped Only', 'src.maturity.known': 'Pending Only',
                'src.search.placeholder': 'Search source URL...',
                'src.limitToggle': 'Top 50 only',
                'src.limitToggle.title': 'Render top 50 only · faster response',
                'quality.title': 'Feed',
                'quality.cnProxy': '🛜 CN Proxy',
                'quality.cnProxy.totalSources': 'Total Sources',
                'quality.cnProxy.available': 'Available',
                'quality.cnProxy.totalProxies': 'Total Proxies',
                'quality.cnProxy.lastDiscovery': 'Last Discovery',
                'quality.cnProxy.sources': 'Proxy Sources',
                'src.title': 'Feed Mill',
                'node.col.score': 'Quality', 'node.col.round': 'Round',
                'node.col.streak': 'Streak', 'node.col.avgSpeed': 'Avg Speed',
                'node.col.latest': 'Latest', 'node.col.probe': 'Probe',
                'src.col.url': 'Source URL', 'src.col.avgScore': 'Avg',
                'src.col.nodeCount': 'Nodes', 'src.col.lowStreak': 'Low Streak',
                'src.col.maturity': 'Maturity', 'src.col.status': 'Status',
                'src.col.trend': 'Trend',
                'src.section.progress': '📊 Round Progress (6h)', 'src.section.poolStats': '🌐 Round Stats',
                'src.round.tested': 'Tested', 'src.round.alive': 'Alive', 'src.round.media': 'Media', 'src.round.speed': 'Speed',
                'src.round.totalNodes': 'Nodes', 'src.round.protocols': 'Protocols', 'src.round.lastRun': 'Last Run',
                'src.section.roundHistory': '📈 Round Trend (6h)',
                'src.section.progress': '📊 Round Progress (6h)',
                'src.section.poolStats': '🌐 Round Stats',
                'src.round.tested': 'Tested', 'src.round.alive': 'Alive',
                'src.round.media': 'Media OK', 'src.round.speed': 'Speed OK',
                'src.round.totalNodes': 'Available', 'src.round.protocols': 'Protocols',
                'src.round.lastRun': 'Last Round',
            },
        };

        const I18N_LS_KEY = 'ss-monitor.lang';
        let __lang = (() => {
            try { return localStorage.getItem(I18N_LS_KEY) || 'zh-Hant'; }
            catch (e) { return 'zh-Hant'; }
        })();

        // 翻译函数: t('key') → 当前语言, fallback zh-Hant
        function t(key) {
            const dict = I18N[__lang] || I18N['zh-Hant'];
            return dict[key] ?? I18N['zh-Hant'][key] ?? key;
        }

        // 应用 i18n 到 [data-i18n]/[data-i18n-placeholder]/[data-i18n-title] 元素
        function applyI18n() {
            document.querySelectorAll('[data-i18n]').forEach(el => {
                const key = el.getAttribute('data-i18n');
                el.textContent = t(key);
            });
            document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
                el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
            });
            document.querySelectorAll('[data-i18n-title]').forEach(el => {
                el.title = t(el.getAttribute('data-i18n-title'));
            });
            // 高亮 active 按钮
            document.querySelectorAll('#langSwitch button').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.lang === __lang);
            });
            // 切语言后用 lang 属性辅助系统字体匹配
            document.documentElement.lang = __lang;
        }

        function setLang(lang) {
            if (!I18N[lang]) return;
            __lang = lang;
            try { localStorage.setItem(I18N_LS_KEY, lang); } catch (e) {}
            applyI18n();
            // 触发动态内容重渲染 (JS 字符串里有 t() 引用)
            try { typeof refreshAll === 'function' && refreshAll(); } catch (e) {}
        }

        // 切换器点击
        document.addEventListener('click', (e) => {
            const btn = e.target.closest('#langSwitch button[data-lang]');
            if (btn) setLang(btn.dataset.lang);
        });

        // ===== DOM 緩存 (Step 15: getElementById 緩存, isConnected 自愈) =====
        const __domCache = new Map();
        function $id(id) {
            let el = __domCache.get(id);
            if (el && el.isConnected) return el;
            el = document.getElementById(id);
            if (el) __domCache.set(id, el);
            else __domCache.delete(id);
            return el;
        }

        // ===== 條件請求 (Step 17: ETag 快取, 304 直接回上次 body) =====
        const __etagCache = new Map();
        async function fetchCached(url) {
            const prev = __etagCache.get(url);
            const headers = prev ? { 'If-None-Match': prev.etag } : {};
            const r = await fetch(url, { headers });
            if (r.status === 304 && prev) return prev.data;
            if (!r.ok) throw new Error(`${url} → ${r.status}`);
            const data = await r.json();
            const etag = r.headers.get('ETag');
            if (etag) __etagCache.set(url, { etag, data });
            return data;
        }

        // ===== 工具函數 =====
        // ---- console guard (Phase A3): 生产环境只保留 error, log/warn 走 dbg, 默认静默 ----
        const __DEBUG = (() => {
            try {
                if (location.hostname === 'localhost' || location.hostname === '127.0.0.1') return true;
                return new URLSearchParams(location.search).has('debug');
            } catch (e) { return false; }
        })();
        const dbg = {
            log:  __DEBUG ? console.log.bind(console)   : () => {},
            warn: __DEBUG ? console.warn.bind(console)  : () => {},
            info: __DEBUG ? console.info.bind(console)  : () => {},
            error: console.error.bind(console),  // error 永远输出, 运维需要
        };

        // ---- HTML escape (防 XSS, 用户字段进 innerHTML 之前必须包) ----
        const __htmlEntityMap = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
        function esc(s) {
            if (s == null) return '';
            return String(s).replace(/[&<>"']/g, c => __htmlEntityMap[c]);
        }
        // URL 协议白名单 (防 javascript:/data: 等 href 注入)
        function safeUrl(u) {
            if (!u) return '#';
            const s = String(u).trim();
            return /^https?:\/\//i.test(s) ? s : '#';
        }
        // 智能 URL 顯示: host + 路徑最後一段, hover 顯示完整
        function smartUrl(url, maxLen) {
            if (!url) return { text: '', full: '' };
            try {
                const u = new URL(url);
                const host = u.hostname.replace(/^www\./, '');
                const parts = u.pathname.split('/').filter(Boolean);
                const last = parts.length > 0 ? parts[parts.length - 1] : '';
                const hash = u.hash || '';
                const label = last ? `${host}/${last}${hash}` : host;
                return { text: label, full: url };
            } catch {
                const s = String(url);
                return { text: s.length > (maxLen||60) ? s.slice(0, maxLen||60) + '…' : s, full: s };
            }
        }

        function fmtBytes(b) {
            if (b == null) return '—';
            if (b < 1024) return `${b} B`;
            if (b < 1024 * 1024) return `${(b/1024).toFixed(1)} KB`;
            if (b < 1024 ** 3) return `${(b/1024/1024).toFixed(1)} MB`;
            if (b < 1024 ** 4) return `${(b/1024/1024/1024).toFixed(2)} GB`;
            return `${(b/1024/1024/1024/1024).toFixed(2)} TB`;
        }
        function fmtRate(b) {
            if (b == null) return '—';
            if (b < 1024) return `${b} B/s`;
            if (b < 1024 * 1024) return `${(b/1024).toFixed(1)} KB/s`;
            return `${(b/1024/1024).toFixed(2)} MB/s`;
        }
        function pctClass(pct) {
            if (pct >= 85) return 'err';
            if (pct >= 65) return 'warn';
            return 'ok';
        }

        function scorePillClass(score) {
            // v3.0 三态机阈值: ≥90 优秀, 70+ 良好, 50+ 中等 (testing 主区), <50 弱 (recovering 区)
            if (score >= 90) return 's-elite';
            if (score >= 70) return 's-good';
            if (score >= 50) return 's-mid';
            return 's-low';
        }
        function speedTextFor(kbps) {
            if (!kbps) return '—';
            return kbps >= 1024 ? `${(kbps/1024).toFixed(1)}MB/s` : `${kbps}KB/s`;
        }
        function setBadge(el, text, cls) {
            el.innerHTML = `<span class="dot"></span>${text}`;
            el.className = `badge ${cls}`;
        }

        // ═══════════════ 表格三檔限制 (5 → mid → all) ═══════════════
        // 狀態存 localStorage, 持久化用戶選擇.
        // stage=0: 顯示 5 行 (默認)
        // stage=1: 顯示 mid 行 (nodeTable=100, srcTable=50; 數量不夠則跳過此檔)
        // stage=2: 顯示全部
        const TABLE_LIMIT_KEY = 'ss-monitor.table-limits';
        function getTableStage(tableId) {
            try {
                const saved = JSON.parse(localStorage.getItem(TABLE_LIMIT_KEY) || '{}');
                return saved[tableId] ?? 0;  // 默認 5 行
            } catch { return 0; }
        }
        function setTableStage(tableId, stage) {
            try {
                const saved = JSON.parse(localStorage.getItem(TABLE_LIMIT_KEY) || '{}');
                saved[tableId] = stage;
                localStorage.setItem(TABLE_LIMIT_KEY, JSON.stringify(saved));
            } catch {}
        }
        // 計算當前檔顯示行數 + 上下檔的數字 (用於 "展開/收起" 文案)
        // mid: 中間檔行數, 0 = 跳過 (數據量 < 5+mid)
        // 返回:
        //   take: 當前要渲染的行數
        //   nextStage / nextLabel: 下一檔 (展開) 信息, null 表示已到頂
        //   prevStage / prevLabel: 上一檔 (收起) 信息, null 表示已默認
        function computeLimit(stage, total, mid) {
            const fiveRows = 5;
            if (total <= fiveRows) return { take: total, nextStage: null, nextLabel: null, prevStage: null, prevLabel: null };
            const labelAll = t('limit.all');
            if (stage === 0) {
                // 默認 5 行 → mid 或全部
                if (mid > 0 && total > mid) {
                    return { take: fiveRows, nextStage: 1, nextLabel: String(mid), prevStage: null, prevLabel: null };
                }
                return { take: fiveRows, nextStage: 2, nextLabel: labelAll, prevStage: null, prevLabel: null };
            }
            if (stage === 1 && mid > 0) {
                // mid → 全部 / 收起 5
                if (total > mid) {
                    return { take: mid, nextStage: 2, nextLabel: labelAll, prevStage: 0, prevLabel: '5' };
                }
                return { take: total, nextStage: null, nextLabel: null, prevStage: 0, prevLabel: '5' };
            }
            // stage 2 全部 → 收起 mid 或 5
            if (mid > 0 && total > mid) {
                return { take: total, nextStage: null, nextLabel: null, prevStage: 1, prevLabel: String(mid) };
            }
            return { take: total, nextStage: null, nextLabel: null, prevStage: 0, prevLabel: '5' };
        }
        // 渲染 "下面還有 N 行 · [展開到 X] · [收起到 Y]" 鏈接
        // wrapper: 包在 <tr><td colspan>...</td></tr> (table=true) 或 <div>...</div>
        // tableId: localStorage key
        // total: 數據總量
        // taken: 當前已渲染數
        // limitInfo: { nextStage, nextLabel, prevStage, prevLabel } 來自 computeLimit
        // rerender: 切換後重渲染的回調
        // table: true=表格 wrap tr/td, false=div wrap (黑名單等列表用)
        // colspan: 僅 table=true 時用
        function _buildLimitLinks(tableId, total, taken, limitInfo, rerender) {
            const links = [];
            const { nextStage, nextLabel, prevStage, prevLabel } = limitInfo;
            // [展開] 鏈接
            if (nextStage != null) {
                const linkId = `expand-${tableId}-${Date.now()}-n`;
                links.push(`<a href="#" id="${linkId}" style="color:var(--sky-400);">${t('limit.expandTo').replace('{label}', nextLabel)}</a>`);
                setTimeout(() => {
                    const el = document.getElementById(linkId);
                    if (el) el.addEventListener('click', (e) => {
                        e.preventDefault();
                        setTableStage(tableId, nextStage);
                        rerender();
                    });
                }, 0);
            }
            // [收起] 鏈接
            if (prevStage != null) {
                const linkId = `collapse-${tableId}-${Date.now()}-p`;
                links.push(`<a href="#" id="${linkId}" style="color:var(--text-3);">${t('limit.collapseTo').replace('{label}', prevLabel)}</a>`);
                setTimeout(() => {
                    const el = document.getElementById(linkId);
                    if (el) el.addEventListener('click', (e) => {
                        e.preventDefault();
                        setTableStage(tableId, prevStage);
                        rerender();
                    });
                }, 0);
            }
            const remaining = total - taken;
            const remainText = remaining > 0 ? `${t('limit.moreBelow').replace('{n}', remaining)} · ` : '';
            const linksText = links.join(' · ');
            return remainText + linksText;
        }
        // 表格用 (返回 <tr>)
        function renderLimitRow(colspan, tableId, total, taken, limitInfo, rerender) {
            if (limitInfo.nextStage == null && limitInfo.prevStage == null) return '';
            const inner = _buildLimitLinks(tableId, total, taken, limitInfo, rerender);
            if (!inner.trim()) return '';
            return `<tr><td colspan="${colspan}" style="text-align:center;color:var(--text-3);font-size:12px;padding:10px;">${inner}</td></tr>`;
        }
        // div 列表用 (返回 <div>)
        function renderLimitDiv(tableId, total, taken, limitInfo, rerender) {
            if (limitInfo.nextStage == null && limitInfo.prevStage == null) return '';
            const inner = _buildLimitLinks(tableId, total, taken, limitInfo, rerender);
            if (!inner.trim()) return '';
            return `<div style="text-align:center;color:var(--text-3);font-size:12px;padding:10px;">${inner}</div>`;
        }
        function tickTimestamp() {
            const el = $id('globalTimestamp');
            if (el) el.textContent = new Date().toLocaleTimeString('zh-CN', { hour12: false });
        }
        setInterval(tickTimestamp, 1000);
        tickTimestamp();

        // ===== 1. SS Monitor =====
        async function loadData() {
            try {
                const data = await fetch('/api/ss-status').then(r => r.json());

                const statusBadge = $id('serviceStatus');
                // 三態: running+有連接=活著(綠) / running 無連接=無人理(黃) / 不 running=救救我(紅)
                let stateText, stateClass, heroClass;
                if (!data.service_running) {
                    stateText = t('ss.state.help');
                    stateClass = 'err';
                    heroClass = 'err';
                } else if ((data.active_connections ?? 0) === 0) {
                    stateText = t('ss.state.lonely');
                    stateClass = 'warn';
                    heroClass = 'warn';
                } else {
                    stateText = t('ss.state.alive');
                    stateClass = 'ok live';
                    heroClass = 'ok';
                }
                setBadge(statusBadge, stateText, stateClass);
                $id('heroSS').classList.remove('ok', 'warn', 'err');
                $id('heroSS').classList.add(heroClass);
                $id('heroSSStatus').textContent = stateText;

                $id('activeConnections').textContent = data.active_connections ?? 0;
                $id('totalConnections').textContent = data.total_connections ?? 0;
                $id('uptime').textContent = data.uptime || '—';
                $id('memory').textContent = data.memory || '—';
                $id('heroSSConn').textContent = `${data.active_connections ?? 0} 活躍 · ${data.total_connections ?? 0} 總`;

                const cl = $id('connectionList');
                if (data.connections && data.connections.length > 0) {
                    cl.innerHTML = data.connections.map(c => {
                        const m = c.match(/^(\S+)\s+\((\d+)\s+連接\)$/);
                        const ip = m ? m[1] : c, n = m ? m[2] : '';
                        return `<div style="display:flex; justify-content:space-between; padding:6px 8px; border-bottom:1px dashed var(--line); font-family:var(--font-mono); font-size:12px;">
                            <span style="color:var(--sky-300);">${ip}</span>
                            <span class="badge cyan">${n} 連接</span>
                        </div>`;
                    }).join('');
                } else {
                    cl.innerHTML = '<div class="empty">暫無活躍連接</div>';
                }
            } catch (e) {
                console.error('SS 加載失敗:', e);
                setBadge($id('serviceStatus'), '檢測失敗', 'err');
            }
        }

        // ===== 2. VPS 服務器狀態 =====
        async function loadVPS() {
            try {
                const d = await fetch('/api/vps-status').then(r => r.json());

                // host info
                $id('vpsHostname').textContent = d.host.hostname;
                $id('vpsOS').textContent = d.host.os;
                $id('vpsKernel').textContent = `${d.host.kernel} / ${d.host.arch}`;
                $id('vpsCpuModel').textContent = d.host.cpu_model;
                $id('vpsUptime').textContent = d.host.uptime_human;
                $id('vpsProc').textContent = `${d.process.running} 運行 / ${d.process.total} 總`;
                $id('vpsHostInfo').textContent = `${d.host.os} · ${d.host.cpu_cores} 核 · ${d.host.uptime_human}`;

                // CPU
                const cpuPct = d.cpu.usage_percent;
                if (cpuPct != null) {
                    $id('vpsCpuValue').innerHTML = `${cpuPct.toFixed(1)}<small>%</small>`;
                    const bar = $id('vpsCpuBar');
                    bar.style.width = cpuPct + '%';
                    bar.className = 'progress-bar ' + pctClass(cpuPct);
                    $id('heroVPSCpu').innerHTML = `${cpuPct.toFixed(0)}<small>% CPU</small>`;
                } else {
                    $id('vpsCpuValue').textContent = '採樣中…';
                    $id('heroVPSCpu').textContent = '—';
                }
                $id('vpsCpuCores').textContent = `· ${d.cpu.cores} 核`;

                // Memory
                const mPct = d.memory.used_percent;
                $id('vpsMemValue').innerHTML = `${mPct.toFixed(1)}<small style="font-size:13px; color:var(--text-3);"> · ${fmtBytes(d.memory.used)} / ${fmtBytes(d.memory.total)}</small>`;
                const mBar = $id('vpsMemBar');
                mBar.style.width = mPct + '%';
                mBar.className = 'progress-bar ' + pctClass(mPct);
                $id('heroVPSMem').textContent = `內存 ${mPct.toFixed(0)}% · 磁盤 ${d.disk.used_percent.toFixed(0)}%`;

                // Disk
                const dPct = d.disk.used_percent;
                $id('vpsDiskValue').innerHTML = `${dPct.toFixed(1)}<small style="font-size:13px; color:var(--text-3);"> · ${fmtBytes(d.disk.used)} / ${fmtBytes(d.disk.total)}</small>`;
                const dBar = $id('vpsDiskBar');
                dBar.style.width = dPct + '%';
                dBar.className = 'progress-bar ' + pctClass(dPct);

                // Swap
                const sPct = d.memory.swap_used_percent;
                if (d.memory.swap_total > 0) {
                    $id('vpsSwapValue').innerHTML = `${sPct.toFixed(1)}<small style="font-size:13px; color:var(--text-3);"> · ${fmtBytes(d.memory.swap_used)} / ${fmtBytes(d.memory.swap_total)}</small>`;
                    const sBar = $id('vpsSwapBar');
                    sBar.style.width = sPct + '%';
                    sBar.className = 'progress-bar ' + (sPct >= 50 ? 'warn' : 'ok');
                } else {
                    $id('vpsSwapValue').textContent = '禁用';
                }

                // Load
                const cores = d.cpu.cores;
                const fmtLoad = (l) => `${l.toFixed(2)}<small style="font-size:12px; color:var(--text-3);"> · ${(l/cores).toFixed(2)}/核</small>`;
                $id('vpsLoad1').innerHTML = fmtLoad(d.cpu.load['1m']);
                $id('vpsLoad5').innerHTML = fmtLoad(d.cpu.load['5m']);
                $id('vpsLoad15').innerHTML = fmtLoad(d.cpu.load['15m']);

                // Network
                $id('vpsIface').textContent = d.network.iface;
                $id('vpsRxRate').innerHTML = fmtRate(d.network.rx_bytes_per_sec);
                $id('vpsTxRate').innerHTML = fmtRate(d.network.tx_bytes_per_sec);
                $id('vpsRxTotal').textContent = fmtBytes(d.network.rx_bytes_total);
                $id('vpsTxTotal').textContent = fmtBytes(d.network.tx_bytes_total);

                // Hero VPS tile state
                const tile = $id('heroVPS');
                tile.classList.remove('ok', 'warn', 'err');
                if (cpuPct >= 85 || mPct >= 90 || dPct >= 90) tile.classList.add('err');
                else if (cpuPct >= 65 || mPct >= 75 || dPct >= 80) tile.classList.add('warn');
                else tile.classList.add('ok');
            } catch (e) {
                console.error('VPS 加載失敗:', e);
                $id('vpsHostInfo').textContent = 'API 錯誤: ' + e.message;
            }
        }

        // ===== 3. 免費節點池 =====
        async function loadFreePool() {
            try {
                const d = await fetch('/api/free-pool').then(r => r.json());

                const ps = $id('poolServiceStatus');
                if (d.service_running) {
                    setBadge(ps, '運行中', 'ok live');
                } else {
                    setBadge(ps, '已停止', 'err');
                }
                $id('poolUptime').textContent = d.service_uptime || '—';
                $id('poolMemory').textContent = d.service_memory || '—';
                $id('poolNextCheck').textContent =
                    (d.progress && d.progress.next_check) || (d.progress && d.progress.completed ? '等待下一輪' : '檢測中');

                // 進度 - completed=true 時顯示"已完成 · 下輪 X 後"; running 時顯示 N/M · pct%
                // 配合「測活」label 旁的 badge: 運行中 / 待機 / —
                // (tested 數字在最後幾秒 subs-check 切換日誌格式後不再更新, 顯示出來會誤導)
                const prog = d.progress || {};

                // ---- 計算 ETA (用於 idle 倒數 + hero 也共用) ----
                let etaText = null;       // "5h21m" / "21m" / null
                let etaImminent = false;  // next_check 已過 → 即將開始
                if (prog.next_check) {
                    const nextMs = new Date(prog.next_check.replace(' ', 'T')).getTime() - Date.now();
                    if (nextMs > 0) {
                        const mins = Math.floor(nextMs / 60000);
                        const hours = Math.floor(mins / 60);
                        const remMins = mins % 60;
                        etaText = hours > 0 ? `${hours}h${remMins}m` : `${remMins}m`;
                    } else {
                        etaImminent = true;
                    }
                }

                // ---- pipeline status badge ----
                const pipelineBadge = $id('poolPipelineStatus');
                if (prog.completed) {
                    setBadge(pipelineBadge, t('pool.pipeline.idle'), 'warn');
                } else if (prog.tested != null && prog.total != null) {
                    setBadge(pipelineBadge, t('pool.pipeline.running'), 'ok live');
                } else {
                    setBadge(pipelineBadge, t('pool.pipeline.unknown'), '');
                }

                // ---- poolTested 主數字 ---- (改用增量探活數據，而非大輪進度)
                // 30min incremental-check 数据
                const inc = d.incremental_check || {};
                if (inc.total_tested != null) {
                    const pct = inc.pass_rate_avg != null ? (inc.pass_rate_avg * 100).toFixed(1) : '?';
                    $id('poolTested').innerHTML = `${inc.total_tested}<small style="font-size:12px; color:var(--text-3);"> · 通過率 ${pct}%</small>`;
                } else {
                    $id('poolTested').textContent = '—';
                }
                $id('poolAlive').textContent = inc.passed ?? '—';
                $id('poolMediaPass').textContent = inc.failed ?? '—';
                const passRate = inc.pass_rate_avg != null ? (inc.pass_rate_avg * 100).toFixed(1) + '%' : '—';
                $id('poolSpeedPass').textContent = passRate;

                // CN 代理數 & 耗時
                $id('poolCnProxies').textContent = inc.cn_proxies_used ?? '—';
                $id('poolElapsed').textContent = inc.elapsed_sec != null ? inc.elapsed_sec.toFixed(0) + 's' : '—';

                // 節點池 (30min incremental-check 状态分布)
                const sd = d.state_distribution || {};
                const totalNodes = Object.values(sd).reduce((a, b) => a + b, 0);
                $id('poolTotalNodes').textContent = totalNodes || '—';

                // 状态 chips (testing/decaying/recovering)
                const protoEl = $id('poolProtocols');
                if (Object.keys(sd).length > 0) {
                    const stateColors = {testing: 'vless', decaying: 'trojan', recovering: 'ss'};
                    protoEl.innerHTML = Object.entries(sd)
                        .sort((a, b) => b[1] - a[1])
                        .map(([k, v]) => `<span class="chip ${stateColors[k] || ''}">${k}<span class="chip-num">${v}</span></span>`).join('');
                } else {
                    protoEl.innerHTML = '<span class="chip">—</span>';
                }

                $id('poolLastRun').textContent = inc.timestamp
                    ? new Date(inc.timestamp).toLocaleString('zh-CN', {month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit'})
                    : '—';

                // Hero pool tile (30min incremental-check) — 全部用增量探活數據
                $id('heroPoolNodes').innerHTML = `${inc.total_tested || '—'}<small>已測試</small>`;
                if (inc.timestamp) {
                    const pr = inc.pass_rate_avg != null ? (inc.pass_rate_avg * 100).toFixed(0) + '%' : '';
                    $id('heroPoolProg').textContent = `通過率 ${pr} · ${inc.passed ?? 0} 通過`;
                } else {
                    $id('heroPoolProg').textContent = `等待首次探活`;
                }
                $id('heroPool').classList.remove('ok','warn','err');
                $id('heroPool').classList.add('ok');

                // Hero 飼料廠（與飼料廠 section 同源）
                const sdb = d.sources_db || {};
                $id('heroSrcCount').innerHTML = `${sdb.total_sources ?? '—'}<small>源</small>`;
                // maturity_counts 在 /api/free-pool/sources 裡，此處先顯示總數，maturity 由 sources fetch 更新
                $id('heroSrcMaturity').textContent = `共 ${sdb.total_sources ?? 0} 源`;
                $id('heroSrc').classList.remove('warn','err','ok');
                $id('heroSrc').classList.add('ok');

                // 評分庫
                $id('dbTotalSources').textContent = sdb.total_sources ?? '—';
                $id('dbStatusCounts').textContent = sdb.status_counts
                    ? Object.entries(sdb.status_counts).map(([k, v]) => `${k}:${v}`).join(' · ')
                    : '—';
                $id('dbLastSync').textContent = sdb.last_sync_at
                    ? new Date(sdb.last_sync_at).toLocaleString('zh-CN')
                    : '—';

                // TOP 5 候選源
                const topEl = $id('dbTopSources');
                if (sdb.top_sources && sdb.top_sources.length > 0) {
                    topEl.innerHTML = sdb.top_sources.map(s => {
                        const su = smartUrl(s.url);
                        return `<div class="src-row">
                            <span class="score">${(s.score || 0).toFixed(1)}</span>
                            <span class="pass">${s.passes}/${s.checks}</span>
                            <a href="${safeUrl(s.url)}" target="_blank" rel="noopener" title="${esc(su.full)}">${esc(su.text)}</a>
                        </div>`;
                    }).join('');
                } else {
                    topEl.innerHTML = '<div class="empty">暫無數據</div>';
                }

                const blEl = $id('dbBlacklisted');
                if (sdb.blacklisted && sdb.blacklisted.length > 0) {
                    blEl.innerHTML = sdb.blacklisted.map(b => {
                        const until = b.until ? new Date(b.until).toLocaleString('zh-CN') : '—';
                        const su = smartUrl(b.url);
                        return `<div class="src-row bl">
                            <span class="score">⛔</span>
                            <span class="pass">${until}</span>
                            <a href="${b.url}" target="_blank" rel="noopener" title="${esc(su.full)}">${esc(su.text)}</a>
                        </div>`;
                    }).join('');
                } else {
                    blEl.innerHTML = '<div class="empty" style="color:var(--good);">✓ 無黑名單源</div>';
                }
            } catch (e) {
                console.error('免費池加載失敗:', e);
                setBadge($id('poolServiceStatus'), 'API 錯誤', 'err');
            }
        }

        // ===== 4. 節點表 / Diff / 歷史 =====
        let __allNodes = [];

        async function loadNodesAndDiff() {
            try {
                const [nr, dr, hr] = await Promise.all([
                    fetchCached('/api/free-pool/nodes'),
                    fetchCached('/api/free-pool/diff'),
                    fetchCached('/api/free-pool/incremental-history'),
                ]);

                $id('diffAdded').textContent = '↑+' + (dr.added_count ?? 0);
                $id('diffRemoved').textContent = '↓-' + (dr.removed_count ?? 0);
                $id('diffKept').textContent = dr.kept_count ?? 0;

                // 增量探活趨勢 (含 pass/fail bar)
                const hl = $id('historyList');
                if (hr.history && hr.history.length > 0) {
                    hl.innerHTML = hr.history.slice().reverse().map(h => {
                        const dt = new Date(h.timestamp);
                        const total = h.total_tested || 0;
                        const passed = h.passed || 0;
                        const failed = h.failed || 0;
                        const passW = total > 0 ? (passed / total * 100).toFixed(0) : 0;
                        const failW = total > 0 ? (failed / total * 100).toFixed(0) : 0;
                        const prPct = (h.pass_rate_avg * 100).toFixed(0);
                        const prColor = h.pass_rate_avg >= 0.7 ? 'var(--good)' : h.pass_rate_avg >= 0.4 ? 'var(--warn)' : 'var(--err)';
                        const meta = [];
                        if (h.cn_proxies_used) meta.push(`<span class="badge cyan">CN×${h.cn_proxies_used}</span>`);
                        if (h.decaying) meta.push(`<span class="badge warn">▼${h.decaying}</span>`);
                        if (h.recovering) meta.push(`<span class="badge err">▲${h.recovering}</span>`);
                        meta.push(`<span style="color:var(--text-3); font-family:var(--font-mono); font-size:11px;">${h.elapsed_sec || 0}s</span>`);
                        return `<div class="history-item">
                            <span class="round-id" style="color:${prColor};">${prPct}%</span>
                            <div>
                                <span class="round-time">${dt.toLocaleString('zh-CN', {month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit'})}</span>
                                <div class="history-bar">
                                    <div style="width:${passW}%; background:var(--good);"></div>
                                    <div style="width:${failW}%; background:var(--err);"></div>
                                </div>
                            </div>
                            <span class="round-nodes">${passed}/${total}</span>
                            <div style="display:flex; flex-wrap:wrap; gap:4px; align-items:center;">${meta.join('')}</div>
                        </div>`;
                    }).join('');
                } else {
                    hl.innerHTML = '<div class="empty">暫無歷史數據</div>';
                }

                __allNodes = nr.nodes || [];
                renderNodeTable();
            } catch (e) {
                console.error('節點數據加載失敗:', e);
            }
        }

        function renderNodeTable() {
            const filter = $id('nodeFilter').value.toLowerCase();
            const sort = $id('nodeSort').value;

            let nodes = __allNodes.filter(n => {
                if (!filter) return true;
                const blob = (n.name + ' ' + n.type + ' ' + (n.region || '') + ' ' + n.server).toLowerCase();
                return blob.includes(filter);
            });

            nodes.sort((a, b) => {
                if (sort === 'quality_desc') return (b.quality_score || 0) - (a.quality_score || 0);
                if (sort === 'speed_desc') return (b.speed_kbps || 0) - (a.speed_kbps || 0);
                if (sort === 'speed_asc') return (a.speed_kbps || 0) - (b.speed_kbps || 0);
                if (sort === 'appearances') return (b.appearances || 0) - (a.appearances || 0);
                if (sort === 'region') return (a.region || 'ZZ').localeCompare(b.region || 'ZZ');
                if (sort === 'type') return a.type.localeCompare(b.type);
                return 0;
            });

            $id('nodeCount').textContent = `${nodes.length} / ${__allNodes.length}`;

            const body = $id('nodeTableBody');
            if (nodes.length === 0) {
                body.innerHTML = '<tr><td colspan="8"><div class="empty">無匹配節點</div></td></tr>';
                return;
            }

            // 三檔限制: 5 → 100 → 全部 (持久化於 localStorage 'ss-monitor.table-limits')
            const stage = getTableStage('nodeTable');
            const limitInfo = computeLimit(stage, nodes.length, 100);
            const { take } = limitInfo;
            const renderNodes = nodes.slice(0, take);

            body.innerHTML = renderNodes.map(n => {
                const speedColor = n.speed_kbps >= 1024 ? 'var(--good)' :
                                   n.speed_kbps >= 700 ? 'var(--sky-400)' :
                                   n.speed_kbps >= 512 ? 'var(--warn)' : 'var(--text-3)';
                const speedText = speedTextFor(n.speed_kbps);
                const score = n.quality_score || 0;
                const consecHigh = (n.consecutive || 0) >= 3 ? 'var(--good)' : 'var(--text-2)';
                // v3.0: state 替代 blacklisted
                const state = n.state || 'testing';
                const stateBadge = state === 'decaying' ? '<span title="decaying: 满分顶到位, 被动衰减" style="color:var(--good); font-size:10px;">▼</span>' :
                                   state === 'recovering' ? '<span title="recovering: 触底, 被动恢复" style="color:var(--err); font-size:10px;">▲</span>' :
                                   '<span title="testing: 主测试态" style="color:var(--sky-400); font-size:10px;">●</span>';
                const subTag = n.sub_tag ? `<div style="color:var(--text-3); font-size:10px; margin-top:2px;" title="${esc(n.sub_tag)}">${esc(n.sub_tag.length > 28 ? n.sub_tag.slice(0, 28) + '…' : n.sub_tag)}</div>` : '';
                return `<tr>
                    <td class="name-cell" title="${esc(n.name)}${n.sub_tag ? ' (' + esc(n.sub_tag) + ')' : ''}">${stateBadge} ${esc(n.name)}${subTag}</td>
                    <td><span class="score-pill ${scorePillClass(score)}">${score.toFixed(0)}</span></td>
                    <td><span class="chip ${n.type}" style="font-size:10px;">${n.type}</span></td>
                    <td class="col-hide-sm">${n.region || '—'}</td>
                    <td style="color:${speedColor}; font-weight:600;">${speedText}</td>
                    <td class="col-hide-sm" style="color:var(--text-3);">${n.appearances || 1}</td>
                    <td class="col-hide-sm" style="color:${consecHigh};">${n.consecutive || 1}</td>
                    <td class="col-hide-sm">${n.tls ? '🔒' : ''}</td>
                </tr>`;
            }).join('') + renderLimitRow(8, 'nodeTable', nodes.length, take, limitInfo, renderNodeTable);
        }
        $id('nodeFilter').addEventListener('input', renderNodeTable);
        $id('nodeSort').addEventListener('change', renderNodeTable);

        // ===== 5. 節點級評分系統 =====
        async function loadQuality() {
            try {
                const r = await fetch('/api/free-pool/quality');
                if (!r.ok) {
                    if (r.status === 503) {
                        $id('qBands').innerHTML = '<div class="empty">history.db 尚未生成 (subs-check 跑完一輪後即出)</div>';
                        return;
                    }
                    throw new Error('HTTP ' + r.status);
                }
                const d = await r.json();

                const s = d.summary || {};
                $id('qTotal').textContent = s.total ?? '—';
                $id('qActive').textContent = s.active ?? '—';
                $id('qBlacklisted').textContent = s.blacklisted ?? '—';

                // bands 柱狀圖 (從高分到低分排序, <30 危險放最後)
                const bandsRaw = d.score_bands || [];
                // 排序: 從每個 band 名稱抓首個數字, 高的在前; <X 視為 -1 排最後
                const bandOrder = b => {
                    const m = b.band.match(/^(\d+)/);
                    if (m) return -parseInt(m[1], 10);  // 90 → -90, 70 → -70, 排序時越小越前
                    return 999;  // <30 / <20 等沒有起始數字的, 排最後
                };
                const bands = bandsRaw.slice().sort((a, b) => bandOrder(a) - bandOrder(b));
                const maxBand = Math.max(...bands.map(b => b.count), 1);
                const bandColors = {
                    // v2.3 滿分制區間
                    '90-100 (優秀)': 'var(--good)',
                    '70-89 (良好)': 'var(--sky-400)',
                    '50-69 (中等)': 'var(--warn)',
                    '30-49 (弱)': 'var(--text-3)',
                    '<30 (危險)': 'var(--err)',
                    // 兼容 v1 舊文案 (回滾後仍可顯示)
                    '80-100 (極品)': 'var(--good)',
                    '60-79 (優秀)': 'var(--sky-400)',
                    '40-59 (中等)': 'var(--warn)',
                    '20-39 (弱)': 'var(--text-3)',
                    '<20 (垃圾)': 'var(--neutral)',
                };
                const bandsEl = $id('qBands');
                if (bands.length === 0) {
                    bandsEl.innerHTML = '<div class="empty">暫無評分數據</div>';
                } else {
                    bandsEl.innerHTML = bands.map(b => {
                        const pct = (b.count / maxBand * 100).toFixed(1);
                        const color = bandColors[b.band] || 'var(--sky-400)';
                        return `<div class="score-band-row">
                            <div class="score-band-head">
                                <span style="color:${color}; font-weight:600;">${b.band}</span>
                                <span style="color:var(--text-3); font-variant-numeric:tabular-nums;">${b.count} 節點</span>
                            </div>
                            <div class="score-band-bar">
                                <div class="score-band-fill" style="width:${pct}%; background:${color}; color:${color};"></div>
                            </div>
                        </div>`;
                    }).join('');
                }

                // TOP 30 (三檔: 5 → 全部, 數量不夠 mid 100 所以跳)
                const topBody = $id('qTopBody');
                const top = d.top_nodes || [];
                if (top.length === 0) {
                    topBody.innerHTML = '<tr><td colspan="9"><div class="empty">暫無數據</div></td></tr>';
                } else {
                    const stage = getTableStage('qTopBody');
                    const limitInfo = computeLimit(stage, top.length, 0);
                    const { take } = limitInfo;
                    const renderTop = top.slice(0, take);
                    topBody.innerHTML = renderTop.map(n => {
                        const sc = n.quality_score || 0;
                        const incTotal = (n.inc_pass || 0) + (n.inc_fail || 0);
                        const incRatio = incTotal > 0 ? `${n.inc_pass}/${incTotal}` : '—';
                        const incColor = n.inc_fail === 0 && n.inc_pass > 0 ? 'var(--good)'
                                       : n.inc_fail >= 2 ? 'var(--err)' : 'var(--text-2)';
                        return `<tr>
                            <td class="name-cell" title="${esc(n.name || n.sig)}">${esc(n.name || n.sig)}</td>
                            <td><span class="score-pill ${scorePillClass(sc)}">${sc.toFixed(0)}</span></td>
                            <td><span class="chip ${n.protocol || ''}" style="font-size:10px;">${n.protocol || '—'}</span></td>
                            <td class="col-hide-sm">${n.region || '—'}</td>
                            <td>${speedTextFor(n.avg_speed_kbps)}</td>
                            <td class="col-hide-sm" style="color:var(--text-2);">${speedTextFor(n.last_speed_kbps)}</td>
                            <td class="col-hide-sm" style="color:var(--text-3);">${n.appearances}</td>
                            <td class="col-hide-sm" style="color:${(n.consecutive || 0) >= 3 ? 'var(--good)' : 'var(--text-2)'};">${n.consecutive}</td>
                            <td class="col-hide-sm" style="color:${incColor}; font-family: var(--font-mono);">${incRatio}</td>
                        </tr>`;
                    }).join('') + renderLimitRow(9, 'qTopBody', top.length, take, limitInfo, () => loadQuality());
                }

                // 黑名單 (三檔: 5 → 全部, 數據量通常 < 100 跳過 mid)
                const blEl = $id('qBlacklistList');
                const bl = d.blacklist || [];
                if (bl.length === 0) {
                    blEl.innerHTML = '<div class="empty" style="color:var(--good);">✓ 無節點級黑名單</div>';
                } else {
                    const stage = getTableStage('qBlacklist');
                    const limitInfo = computeLimit(stage, bl.length, 0);
                    const { take } = limitInfo;
                    const renderBl = bl.slice(0, take);
                    blEl.innerHTML = renderBl.map(b => {
                        const until = b.until ? new Date(b.until).toLocaleString('zh-CN') : '—';
                        return `<div class="src-row bl">
                            <span class="score">⛔</span>
                            <span class="pass" style="font-family: var(--font-mono);">${b.region || '—'}·${b.protocol || '—'}</span>
                            <div style="display:flex; justify-content:space-between; gap:10px;">
                                <span style="color:var(--text-2); font-family:var(--font-mono); font-size:11px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${b.sig}</span>
                                <span style="color:var(--text-3); font-size:11px;">解封 ${until}</span>
                            </div>
                        </div>`;
                    }).join('') + renderLimitDiv('qBlacklist', bl.length, take, limitInfo, () => loadQuality());
                }

                // CN 代理探活
                const cnProxy = d.cn_proxy;
                const cnStatsEl = $id('qCnProxyStats');
                const cnSrcEl = $id('qCnProxySources');
                if (!cnProxy || cnProxy.error) {
                    if (cnStatsEl) cnStatsEl.innerHTML = '';
                    if (cnSrcEl) cnSrcEl.innerHTML = `<div class="empty">${cnProxy ? cnProxy.error : 'cn-proxy-sources.db 尚未生成'}</div>`;
                } else {
                    // 摘要统计
                    if (cnStatsEl) {
                        const lastDisc = cnProxy.last_discovery
                            ? new Date(cnProxy.last_discovery).toLocaleString(__lang === 'en' ? 'en-US' : 'zh-TW')
                            : '—';
                        cnStatsEl.innerHTML = `
                            <div class="stat-tile"><div class="label">${t('quality.cnProxy.totalSources')}</div><div class="value">${cnProxy.total_sources}</div></div>
                            <div class="stat-tile"><div class="label">${t('quality.cnProxy.available')}</div><div class="value" style="color:var(--good);">${cnProxy.available_sources}</div></div>
                            <div class="stat-tile"><div class="label">${t('quality.cnProxy.totalProxies')}</div><div class="value">${cnProxy.total_proxies.toLocaleString()}</div></div>
                            <div class="stat-tile"><div class="label">${t('quality.cnProxy.lastDiscovery')}</div><div class="value"><span style="font-size:13px;font-weight:500;">${lastDisc}</span></div></div>
                        `;
                    }
                    // 源列表 (5行三段式)
                    if (cnSrcEl) {
                        const sources = cnProxy.sources || [];
                        if (sources.length === 0) {
                            cnSrcEl.innerHTML = '<div class="empty">無代理源</div>';
                        } else {
                            function _renderCnProxyList() {
                                const lim = computeLimit(_cnSrcStage, sources.length, 0);
                                const visible = sources.slice(0, lim.take);
                                const rows = visible.map(src => {
                                    const statusColor = src.status === 'ok' ? 'var(--good)' : src.status === 'fail' ? 'var(--err)' : 'var(--warn)';
                                    const statusIcon = src.status === 'ok' ? '✓' : src.status === 'fail' ? '✗' : '?';
                                    const checked = src.last_checked
                                        ? new Date(src.last_checked).toLocaleString(__lang === 'en' ? 'en-US' : 'zh-TW')
                                        : '—';
                                    return `<div class="kv-row">
                                        <div class="k" style="display:flex;align-items:center;gap:6px;min-width:0;">
                                            <span style="color:${statusColor};font-weight:600;">${statusIcon}</span>
                                            <span class="chip ${src.protocol}">${src.protocol}</span>
                                            <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(src.name)}</span>
                                        </div>
                                        <div class="v">
                                            <span style="color:var(--text-2);">${src.proxy_count}</span>
                                            <span style="color:var(--text-3);font-size:11px;">${checked}</span>
                                        </div>
                                    </div>`;
                                }).join('');
                                const limitHtml = _buildLimitLinks('cnSrc', sources.length, lim.take, lim, _renderCnProxyList);
                                cnSrcEl.innerHTML = rows + (limitHtml ? `<div style="text-align:center;color:var(--text-3);font-size:12px;padding:8px 0;">${limitHtml}</div>` : '');
                            }
                            let _cnSrcStage = 0;
                            _renderCnProxyList();
                        }
                    }
                }
            } catch (e) {
                console.error('節點質量加載失敗:', e);
                $id('qBands').innerHTML = `<div class="empty" style="color:var(--err);">加載失敗: ${e.message}</div>`;
            }
        }

        // ===== 6. 源級評分系統 =====
        let __allSources = [];
        let __srcThresholds = { kill: 5, cutoff: 50, grace: 28 };

        async function loadSources() {
            try {
                const r = await fetch('/api/free-pool/sources');
                if (!r.ok) {
                    if (r.status === 503) {
                        $id('srcTableBody').innerHTML = '<tr><td colspan="7"><div class="empty">source-scores.db 尚未生成</div></td></tr>';
                        return;
                    }
                    throw new Error('HTTP ' + r.status);
                }
                const d = await r.json();

                __srcThresholds.kill = d.kill_threshold_lq ?? d.kill_threshold ?? 5;
                __srcThresholds.cutoff = d.low_quality_cutoff ?? 50;
                __srcThresholds.kill_total = d.kill_threshold_lst ?? 15;
                __srcThresholds.low_score = d.low_score_cutoff ?? 30;
                __srcThresholds.fail = d.fail_threshold_candidate ?? 3;
                // 閾值顯示
                const _kt = $id('srcKillTotal');        if (_kt) _kt.textContent = __srcThresholds.kill_total;
                const _lc = $id('srcLowScoreCutoff');   if (_lc) _lc.textContent = __srcThresholds.low_score;
                const _ft = $id('srcFailThreshold');    if (_ft) _ft.textContent = __srcThresholds.fail;

                // 成熟度統計
                const mc = d.maturity_counts || {};
                $id('srcMatScored').textContent = mc.scored ?? '—';
                $id('srcMatMapped').textContent = mc.mapped ?? '—';
                $id('srcMatKnown').textContent = mc.known ?? '—';

                // 同步 Hero 飼料廠 maturity
                $id('heroSrcMaturity').textContent = `🟢${mc.scored ?? 0} · 🟡${mc.mapped ?? 0} · ⚪${mc.known ?? 0}`;

                __allSources = d.sources || [];
                renderSourceTable();
            } catch (e) {
                console.error('源級評分加載失敗:', e);
                $id('srcTableBody').innerHTML = `<tr><td colspan="7"><div class="empty" style="color:var(--err);">加載失敗: ${e.message}</div></td></tr>`;
            }
        }

        function buildSparkline(trend) {
            if (!trend || trend.length === 0) return '<span style="color:var(--text-3);">—</span>';
            const data = trend.slice().reverse();
            const w = 80, h = 18;
            const max = Math.max(...data.map(p => p.avg), 100);
            const min = Math.min(...data.map(p => p.avg), 0);
            const range = max - min || 1;
            const stepX = data.length > 1 ? w / (data.length - 1) : 0;
            const pts = data.map((p, i) => {
                const x = i * stepX;
                const y = h - ((p.avg - min) / range) * h;
                return `${x.toFixed(1)},${y.toFixed(1)}`;
            }).join(' ');
            const lastBelow = data[data.length - 1]?.below_50;
            const lineColor = lastBelow ? 'var(--err)' : 'var(--good)';
            return `<svg class="sparkline" width="${w}" height="${h}">
                <polyline points="${pts}" fill="none" stroke="${lineColor}" stroke-width="1.5"/>
            </svg>`;
        }

        function renderSourceTable() {
            const filter = $id('srcFilter').value.toLowerCase();
            const sort = $id('srcSort').value;
            const matFilter = $id('srcMaturityFilter').value;
            const matRank = { scored: 3, mapped: 2, known: 1 };

            let sources = __allSources.filter(s => {
                if (matFilter && s.data_maturity !== matFilter) return false;
                if (filter && !s.url.toLowerCase().includes(filter)) return false;
                return true;
            });

            sources.sort((a, b) => {
                if (sort === 'score_desc') return (b.latest_avg_score ?? -1) - (a.latest_avg_score ?? -1);
                if (sort === 'score_asc') return (a.latest_avg_score ?? 999) - (b.latest_avg_score ?? 999);
                if (sort === 'count_desc') return (b.latest_node_count || 0) - (a.latest_node_count || 0);
                if (sort === 'streak_desc') return (b.low_streak || 0) - (a.low_streak || 0);
                if (sort === 'maturity') return matRank[b.data_maturity] - matRank[a.data_maturity];
                return 0;
            });

            $id('srcCount').textContent = `${sources.length} / ${__allSources.length}`;

            const body = $id('srcTableBody');
            if (sources.length === 0) {
                body.innerHTML = '<tr><td colspan="7"><div class="empty">無匹配源</div></td></tr>';
                return;
            }

            // 三檔限制: 5 → 50 → 全部
            const stage = getTableStage('srcTable');
            const limitInfo = computeLimit(stage, sources.length, 50);
            const { take } = limitInfo;
            const renderSources = sources.slice(0, take);

            body.innerHTML = renderSources.map(s => {
                const score = s.latest_avg_score;
                const scoreText = score == null ? '—' : score.toFixed(1);
                const scoreCell = score == null
                    ? `<span style="color:var(--text-3);">${scoreText}</span>`
                    : `<span class="score-pill ${scorePillClass(score)}">${scoreText}</span>`;
                const streak = s.low_streak || 0;
                const streakColor = streak >= __srcThresholds.kill ? 'var(--err)' : streak >= 3 ? 'var(--warn)' : 'var(--text-2)';

                const matBadge = {
                    scored: `<span class="badge ok"><span class="dot"></span>${t('status.scored')}</span>`,
                    mapped: `<span class="badge warn"><span class="dot"></span>${t('status.mapped')}</span>`,
                    known: `<span class="badge neutral"><span class="dot"></span>${t('status.known')}</span>`,
                }[s.data_maturity] || '<span class="badge neutral">—</span>';

                // v3.0: state 三态机优先显示, 同时保留 status 兼容
                const state = s.state || 'testing';
                const stateBadge = state === 'decaying'
                    ? `<span class="badge ok" title="decaying: 满分顶到位, 被动衰减"><span class="dot"></span>▼ ${state}</span>`
                    : state === 'recovering'
                    ? `<span class="badge err" title="recovering: 触底, 被动恢复"><span class="dot"></span>▲ ${state}</span>`
                    : `<span class="badge neutral" title="testing: 主测试态"><span class="dot"></span>● ${state}</span>`;

                const statusBadge = s.status === 'blacklisted'
                    ? `<span class="badge err">${t('status.blacklisted')}</span>`
                    : s.status === 'whitelisted'
                    ? `<span class="badge ok">${t('status.whitelisted')}</span>`
                    : `<span class="badge neutral">${t('status.candidate')}</span>`;

                const su = smartUrl(s.url);
                return `<tr>
                    <td class="name-cell" style="max-width:340px;" title="${esc(su.full)}">
                        <a href="${safeUrl(s.url)}" target="_blank" rel="noopener">${esc(su.text)}</a>
                    </td>
                    <td>${scoreCell}</td>
                    <td class="col-hide-sm" style="color:var(--text-2);">${s.latest_node_count ?? '—'}</td>
                    <td class="col-hide-sm" style="color:${streakColor}; font-weight:600;">${streak}</td>
                    <td>${matBadge}</td>
                    <td class="col-hide-sm">${stateBadge}</td>
                    <td class="col-hide-sm">${buildSparkline(s.recent_trend)}</td>
                </tr>`;
            }).join('') + renderLimitRow(7, 'srcTable', sources.length, take, limitInfo, renderSourceTable);
        }
        $id('srcFilter').addEventListener('input', renderSourceTable);
        $id('srcSort').addEventListener('change', renderSourceTable);
        $id('srcMaturityFilter').addEventListener('change', renderSourceTable);

        // ===== 6h 大輪趨勢 (飼料廠卡) =====
        async function loadRoundHistory() {
            const el = $id('srcRoundHistory');
            try {
                // 渲染 6h 大輪 stat tiles (從 /api/free-pool 的 progress + pool)
                const d = await fetchCached('/api/free-pool');
                const prog = d.progress || {};
                const pool = d.pool || {};
                const setOrDash = (id, val) => { const e = $id(id); if (e) e.textContent = val ?? '—'; };
                setOrDash('srcRoundTested', prog.total ?? prog.tested ?? '—');
                setOrDash('srcRoundAlive', prog.alive ?? '—');
                setOrDash('srcRoundMedia', prog.media_pass ?? '—');
                setOrDash('srcRoundSpeed', prog.speed_pass ?? '—');
                setOrDash('srcRoundTotalNodes', pool.total_nodes ?? '—');
                setOrDash('srcRoundLastRun', pool.last_run
                    ? new Date(pool.last_run).toLocaleString('zh-CN', {month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit'})
                    : '—');
                const protoEl = $id('srcRoundProtocols');
                if (protoEl && pool.protocols) {
                    protoEl.innerHTML = Object.entries(pool.protocols)
                        .sort((a, b) => b[1] - a[1])
                        .map(([k, v]) => `<span class="chip ${k}">${k}<span class="chip-num">${v}</span></span>`).join('');
                }

                // 渲染 6h 大輪趨勢圖
                if (!el) return;
                const hr = await fetchCached('/api/free-pool/history');
                if (hr.history && hr.history.length > 0) {
                    const maxNodes = Math.max(...hr.history.map(h => h.total_nodes), 1);
                    el.innerHTML = hr.history.slice().map(h => {
                        const dt = new Date(h.timestamp);
                        const delta = h.diff.added - h.diff.removed;
                        const arrow = delta > 0 ? '↑' : (delta < 0 ? '↓' : '·');
                        const sign = delta > 0 ? '+' : '';
                        const color = delta > 0 ? 'var(--good)' : (delta < 0 ? 'var(--err)' : 'var(--text-3)');
                        const barW = (h.total_nodes / maxNodes * 100).toFixed(0);
                        const protos = Object.entries(h.protocols || {})
                            .sort((a,b) => b[1] - a[1])
                            .slice(0, 8)
                            .map(([k, v]) => `<span class="chip ${k}" style="font-size:10px; padding:1px 6px;">${k}<span class="chip-num">${v}</span></span>`).join('');
                        return `<div class="history-item">
                            <span class="round-id">#${h.round_id}</span>
                            <div>
                                <span class="round-time">${dt.toLocaleString('zh-CN', {month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit'})}</span>
                                <div style="margin-top:3px; background:rgba(0,0,0,0.3); border-radius:3px; height:4px; overflow:hidden;">
                                    <div style="width:${barW}%; height:100%; background:linear-gradient(90deg, var(--sky-500), var(--cyan-400)); box-shadow:0 0 4px rgba(56,189,248,0.4);"></div>
                                </div>
                            </div>
                            <span class="round-nodes">${h.total_nodes}</span>
                            <span class="round-delta" style="color:${color};">${arrow}${sign}${delta}</span>
                            <div class="protos">${protos}</div>
                        </div>`;
                    }).join('');
                } else {
                    el.innerHTML = '<div class="empty">暫無歷史數據</div>';
                }
            } catch (e) {
                dbg.warn('loadRoundHistory failed', e);
            }
        }

        // ===== loadDiscover - discover-airports 卡片 =====
        async function loadDiscover() {
            try {
                const r = await fetch('/api/free-pool/discover');
                if (!r.ok) {
                    dbg.warn('discover endpoint not OK', r.status);
                    return;
                }
                const d = await r.json();
                if (d.error) {
                    dbg.warn('discover error', d.error);
                    return;
                }

                // 頂部 4 個 KV
                const setText = (id, v) => { const el = $id(id); if (el) el.textContent = v; };
                setText('discoverRulesVer', d.rules_version || '—');
                setText('discoverTotalStates', d.total_states ?? '—');
                setText('discoverAdded7d', (d.recent_added_7d || []).length);

                const sevCounts = d.audit_severity_30d || {};
                const auditTotal = Object.values(sevCounts).reduce((a, b) => a + b, 0);
                const critN = sevCounts.critical || 0;
                const warnN = sevCounts.warn || 0;
                const auditTxt = critN > 0
                    ? `${auditTotal} (含 ${critN} critical)`
                    : warnN > 0
                    ? `${auditTotal} (含 ${warnN} warn)`
                    : `${auditTotal}`;
                setText('discoverAuditCount', auditTxt);

                // last run
                if (d.last_run_at) {
                    setText('discoverLastRun', new Date(d.last_run_at).toLocaleString('zh-Hant'));
                } else {
                    setText('discoverLastRun', t('discover.lastRun.never'));
                }

                // kind summary 4 個 stat-tile
                const ks = d.kind_summary || {};
                const fmtKind = (k, hint) => {
                    const v = ks[k];
                    if (!v) return { val: '—', hint: hint };
                    return {
                        val: `${v.scanned_24h}/${v.total} 24h`,
                        hint: `共 ${v.last_added_total} 累計入庫${v.errors > 0 ? ` · ⚠️ ${v.errors} 錯誤` : ''}`,
                    };
                };
                const a = fmtKind('awesome_readme', '—');
                setText('discoverKindAwesome', a.val); setText('discoverKindAwesomeHint', a.hint);
                const tk = fmtKind('github_topic', '—');
                setText('discoverKindTopic', tk.val); setText('discoverKindTopicHint', tk.hint);
                // telegram 默認未啓用, 不變
                // 現有源審計: 從 audit_severity_30d 取 (不在 kind_summary 裡)
                const sev30 = d.audit_severity_30d || {};
                const auditTotal30 = Object.values(sev30).reduce((a, b) => a + b, 0);
                const warnCount = (sev30.warn || 0) + (sev30.critical || 0);
                const adVal = auditTotal30 > 0 ? `${auditTotal30} 條 / 30天` : '—';
                const adHint = auditTotal30 > 0 ? `ℹ️ ${sev30.info || 0} 通過${warnCount > 0 ? ` · ⚠️ ${warnCount} 警告` : ''}` : 'score < 80 才掃';
                setText('discoverKindAudit', adVal); setText('discoverKindAuditHint', adHint);

                // 最近 7 天新增源 (三檔: 5 → 20 → 全部, 與其他列表統一)
                const addedEl = $id('discoverRecentAdded');
                if (addedEl) {
                    const items = d.recent_added_7d || [];
                    if (items.length === 0) {
                        addedEl.innerHTML = `<div class="empty" style="padding:14px; color:var(--text-3); font-size:12px;">${t('discover.empty.added')}</div>`;
                    } else {
                        const stage = getTableStage('discoverRecentAdded');
                        const limitInfo = computeLimit(stage, items.length, 20);
                        const { take } = limitInfo;
                        addedEl.innerHTML = items.slice(0, take).map(s => {
                            const su = smartUrl(s.url);
                            const fs = s.first_seen ? new Date(s.first_seen).toLocaleDateString('zh-Hant') : '—';
                            return `<div class="src-row" title="${esc(su.full)}">
                                <span class="score">${(s.score ?? 100).toFixed(0)}</span>
                                <span class="pass" style="color:var(--text-3);">${fs}</span>
                                <span style="color:var(--text-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${esc(su.text)}</span>
                            </div>`;
                        }).join('') + renderLimitDiv('discoverRecentAdded', items.length, take, limitInfo, () => loadDiscover());
                    }
                }

                // 審計事件 (三檔: 5 → 20 → 全部)
                const auditEl = $id('discoverAuditList');
                if (auditEl) {
                    const items = d.audit_recent_20 || [];
                    if (items.length === 0) {
                        auditEl.innerHTML = `<div class="empty" style="padding:14px; color:var(--text-3); font-size:12px;">${t('discover.empty.audit')}</div>`;
                    } else {
                        const sevColor = sev => sev === 'critical' ? 'var(--err)' : sev === 'warn' ? 'var(--warn)' : 'var(--text-3)';
                        const sevIcon = sev => sev === 'critical' ? '🚨' : sev === 'warn' ? '⚠️' : 'ℹ️';
                        const stage = getTableStage('discoverAuditList');
                        const limitInfo = computeLimit(stage, items.length, 20);
                        const { take } = limitInfo;
                        auditEl.innerHTML = items.slice(0, take).map(a => {
                            const su = smartUrl(a.source_url);
                            const at = a.audited_at ? new Date(a.audited_at).toLocaleString('zh-Hant', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—';
                            const finding = a.finding && a.finding !== 'audit_pass' ? a.finding : (a.severity === 'info' ? '通過' : a.finding || a.severity);
                            return `<div class="src-row audit-row" title="${esc(su.full)}\n${esc(a.finding || '')}">
                                <span class="score" style="color:${sevColor(a.severity)}; font-weight:700;">${sevIcon(a.severity)}</span>
                                <span class="pass" style="color:var(--text-3);">${at}</span>
                                <span class="url-cell" style="color:var(--text-2);">${esc(su.text)}</span>
                                <span class="pass" style="color:${sevColor(a.severity)};">${esc(finding)}</span>
                            </div>`;
                        }).join('') + renderLimitDiv('discoverAuditList', items.length, take, limitInfo, () => loadDiscover());
                    }
                }

                // 隊列詳情 (三檔: 5 → 全部, 數據量 16 < 100 跳 mid)
                const queueBody = $id('discoverQueueBody');
                if (queueBody) {
                    const queue = d.queue || [];
                    if (queue.length === 0) {
                        queueBody.innerHTML = `<tr><td colspan="6"><div class="empty">${t('discover.empty.queue')}</div></td></tr>`;
                    } else {
                        const stage = getTableStage('discoverQueue');
                        const limitInfo = computeLimit(stage, queue.length, 0);
                        const { take } = limitInfo;
                        const renderQueue = queue.slice(0, take);
                        const kindLabel = k => ({
                            awesome_readme: '📖 awesome',
                            github_topic: '🔍 topic',
                            telegram_channel: '💬 telegram',
                            source_audit: '🛡️ audit',
                        })[k] || k;
                        const statusBadge = (s, errs) => {
                            if (!s) return `<span class="badge neutral"><span class="dot"></span>${t('status.notScanned')}</span>`;
                            if (s === 'ok') return `<span class="badge ok"><span class="dot"></span>${t('status.ok')}</span>`;
                            return `<span class="badge err"><span class="dot"></span>${s}</span>`;
                        };
                        queueBody.innerHTML = renderQueue.map(q => {
                            const lastScan = q.last_scanned_at
                                ? new Date(q.last_scanned_at).toLocaleString('zh-Hant', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
                                : '—';
                            return `<tr>
                                <td style="color:var(--text-2); font-size:12px;">${kindLabel(q.kind)}</td>
                                <td class="name-cell" title="${esc(q.key)}" style="max-width:280px;">${esc(q.key)}</td>
                                <td style="font-family:var(--font-mono); color:var(--text-3);">${q.priority ?? '—'}</td>
                                <td style="color:var(--text-3); font-size:11px;">${lastScan}</td>
                                <td>${statusBadge(q.last_status, q.consecutive_empty)}</td>
                                <td style="font-family:var(--font-mono); color:var(--good);">${q.total_added_count ?? 0}</td>
                            </tr>`;
                        }).join('') + renderLimitRow(6, 'discoverQueue', queue.length, take, limitInfo, () => loadDiscover());
                    }
                }
            } catch (e) {
                console.error('loadDiscover failed', e);
            }
        }

        // ===== 刷新 + 調度 =====
        async function refreshAll() {
            const btn = document.querySelector('.refresh-btn');
            if (btn) { btn.style.pointerEvents = 'none'; btn.style.opacity = '0.5'; }
            try {
                await Promise.allSettled([
                    loadData(), loadVPS(), loadFreePool(),
                    loadNodesAndDiff(), loadQuality(), loadSources(), loadRoundHistory(), loadDiscover()
                ]);
            } finally {
                if (btn) { btn.style.pointerEvents = ''; btn.style.opacity = ''; }
            }
        }

        // 初始化
        loadData();
        loadVPS();
        loadFreePool();
        loadNodesAndDiff();
        loadQuality();
        loadSources();
        loadRoundHistory();
        loadDiscover();

        // 定時刷新 · 頁面隱藏時暫停輪詢 (visibility API)
        const _intervals = [];
        function _schedule() {
            // 避免重複建立
            if (_intervals.length) return;
            _intervals.push(setInterval(loadData, 5000));          // SS 狀態 5s
            _intervals.push(setInterval(loadVPS, 5000));           // VPS 狀態 5s
            _intervals.push(setInterval(loadFreePool, 30000));     // 免費池 30s
            _intervals.push(setInterval(loadNodesAndDiff, 60000)); // 節點/diff/趨勢 60s
            _intervals.push(setInterval(loadQuality, 90000));      // 節點級評分 90s
            _intervals.push(setInterval(loadSources, 90000));      // 源級評分 90s
            _intervals.push(setInterval(loadRoundHistory, 60000));  // 大輪趨勢 60s
            _intervals.push(setInterval(loadDiscover, 120000));    // 自動發現 120s (低頻)
        }
        function _clearAll() {
            _intervals.forEach(clearInterval);
            _intervals.length = 0;
        }
        _schedule();
        applyI18n();

        // 頁面隱藏時暫停輪詢, 切回才重啓 (節省後臺流量 + CPU)
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                _clearAll();
            } else {
                // 切回頁面: 先刷一次補上隱藏期間的變化, 再重新排期
                loadData();
                loadVPS();
                loadFreePool();
                _schedule();
            }
        });

        // ===== 卡片折疊 (含 localStorage 跨刷新記憶) =====
        (function initCollapsible() {
            const KEY = 'ss-monitor.collapsed';
            let saved;
            try { saved = JSON.parse(localStorage.getItem(KEY) || '{}'); }
            catch (e) { saved = {}; }

            document.querySelectorAll('.card.collapsible').forEach(card => {
                const id = card.id;
                if (!id) return;

                // 恢復上次狀態 — 默認摺疊, 只有用戶顯式展開過 (存 false) 才展開
                if (saved[id] !== false) card.classList.add('collapsed');

                // ARIA
                const head = card.querySelector('.card-head');
                if (!head) return;
                head.setAttribute('role', 'button');
                head.setAttribute('tabindex', '0');
                const updateAria = () => head.setAttribute('aria-expanded',
                    card.classList.contains('collapsed') ? 'false' : 'true');
                updateAria();

                const toggle = () => {
                    card.classList.toggle('collapsed');
                    updateAria();
                    saved[id] = card.classList.contains('collapsed');
                    try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (e) {}
                };

                head.addEventListener('click', (e) => {
                    // 避免點擊 head 內 <a> / <button> / <code> / <input> 觸發折疊
                    if (e.target.closest('a, button, input, select, textarea')) return;
                    toggle();
                });
                head.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        toggle();
                    }
                });
            });
        })();
    
        // ===== refresh button click handler (Phase C: 移除 inline onclick) =====
        (function() {
            const btn = document.getElementById('refreshBtn');
            if (btn) btn.addEventListener('click', () => {
                if (typeof refreshAll === 'function') refreshAll();
            });
        })();

        // ===== 敏感信息打码显示 (永久打碼, 不可點擊展開) =====
        // 用 JS 重新生成打碼文本, 確保即使 HTML 寫錯也不會洩露原值.
        // 已取消點擊展開: 點擊不會顯示原值, 30 秒自動隱藏 / 點外部收起 全部移除.
        (function() {
            function maskValue(s, mode) {
                if (s == null) return '';
                s = String(s);
                if (s.length === 0) return '';
                if (mode === 'port') {
                    // 端口: 首位 + ***
                    return s.length <= 2 ? '***' : s[0] + '***';
                }
                if (mode === 'domain') {
                    // 域名: 前 3 + *** + 末 3
                    if (s.length <= 6) return '***';
                    return s.slice(0, 3) + '***' + s.slice(-3);
                }
                // generic: 前 3 + *** + 末 3 (短串走全 ***)
                if (s.length <= 6) return '***';
                return s.slice(0, 3) + '***' + s.slice(-3);
            }

            const masked = document.querySelectorAll('.masked');
            masked.forEach(el => {
                const secret = el.getAttribute('data-secret') || '';
                const mode = el.getAttribute('data-mask-mode') || 'generic';
                el.textContent = maskValue(secret, mode);
                el.setAttribute('aria-label', '敏感資訊已隱藏');
                // 移除舊的 cursor:pointer / hover 提示, CSS 會接手樣式
                el.style.cursor = 'default';
            });
        })();
