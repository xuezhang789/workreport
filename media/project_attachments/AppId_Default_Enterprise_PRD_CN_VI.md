
# 需求说明：AppId 默认企业配置与注册归属规则

## 一、需求背景
系统支持多个 App 接入，并基于企业维度进行用户管理。
在部分 App 场景下，用户注册时不强制填写邀请码，需要系统自动确定其企业归属。
为避免不同 App 的用户被错误分配到同一企业，同时提升注册流程的灵活性，需在后台引入 AppId 管理能力，通过 AppId 明确用户在无邀请码注册时的默认企业归属。

---

## Mô tả yêu cầu: Cấu hình doanh nghiệp mặc định theo AppId và quy tắc phân bổ khi đăng ký

### 1. Bối cảnh
Hệ thống hỗ trợ nhiều App và quản lý người dùng theo doanh nghiệp.
Trong một số kịch bản của App, người dùng không bắt buộc phải nhập mã mời khi đăng ký, hệ thống cần tự động xác định doanh nghiệp tương ứng.
Để tránh việc người dùng từ các App khác nhau bị phân bổ nhầm vào cùng một doanh nghiệp, đồng thời nâng cao tính linh hoạt của quy trình đăng ký, cần bổ sung chức năng quản lý AppId ở后台, dùng AppId để xác định doanh nghiệp mặc định khi đăng ký không có mã mời.

---

## 二、需求目标
1. 支持在后台为每个 AppId 配置一个默认企业
2. 用户注册时：
   - 优先使用邀请码确定企业归属
   - 未填写邀请码时，通过 AppId 自动匹配默认企业
3. 确保注册流程清晰、规则统一、结果可预期

---

## 2. Mục tiêu yêu cầu
1. Hỗ trợ cấu hình một doanh nghiệp mặc định cho mỗi AppId ở后台
2. Khi người dùng đăng ký:
   - Ưu tiên sử dụng mã mời để xác định doanh nghiệp
   - Nếu không nhập mã mời, tự động gán doanh nghiệp mặc định theo AppId
3. Đảm bảo quy trình đăng ký rõ ràng, quy tắc thống nhất và kết quả có thể dự đoán

---

## 三、功能范围
- 仅影响用户注册流程
- 不影响登录逻辑
- 不涉及历史用户企业归属调整

---

## 3. Phạm vi chức năng
- Chỉ ảnh hưởng đến quy trình đăng ký người dùng
- Không ảnh hưởng đến logic đăng nhập
- Không liên quan đến việc điều chỉnh doanh nghiệp của người dùng hiện tại

---

## 四、核心功能设计

### 4.1 AppId 管理（后台）
后台新增 AppId 管理模块，支持以下配置项：

| 配置项 | 说明 |
| ---- | ---- |
| AppId | 应用唯一标识 |
| App 名称 | 用于后台识别 |
| 默认企业码 | 无邀请码注册时使用 |
| 状态 | 启用 / 停用 |
| 更新时间 | 用于审计 |

配置规则：
1. 一个 AppId 仅允许配置一个默认企业
2. 默认企业配置仅作用于未填写邀请码的注册场景
3. AppId 被停用后，不允许新用户注册

---

## 4. Thiết kế chức năng cốt lõi

### 4.1 Quản lý AppId (后台)
Thêm mô-đun quản lý AppId ở后台, hỗ trợ các cấu hình sau:

| Trường cấu hình | Mô tả |
| ---- | ---- |
| AppId | Định danh duy nhất của ứng dụng |
| Tên App | Dùng để nhận diện ở后台 |
| Mã doanh nghiệp mặc định | Sử dụng khi đăng ký không có mã mời |
| Trạng thái | Bật / Tắt |
| Thời gian cập nhật | Dùng cho audit |

Quy tắc cấu hình:
1. Mỗi AppId chỉ được cấu hình một doanh nghiệp mặc định
2. Doanh nghiệp mặc định chỉ áp dụng cho trường hợp đăng ký không có mã mời
3. Khi AppId bị vô hiệu hóa, không cho phép người dùng mới đăng ký

---

## 五、注册逻辑说明

### 5.1 注册规则优先级
邀请码优先，AppId 默认企业兜底

---

## 5. Mô tả logic đăng ký

### 5.1 Thứ tự ưu tiên
Ưu tiên mã mời, doanh nghiệp mặc định theo AppId dùng làm phương án dự phòng

---

### 5.2 注册场景一：填写邀请码
处理逻辑：
用户注册（填写邀请码）
→ 校验邀请码有效性
→ 获取邀请码对应的企业
→ 注册成功，用户归属至该企业

说明：
- 与现有邀请码注册逻辑保持一致
- 不受 AppId 默认企业配置影响

---

### 5.2 Trường hợp 1: Đăng ký có mã mời
Luồng xử lý:
Người dùng đăng ký (nhập mã mời)
→ Kiểm tra tính hợp lệ của mã mời
→ Lấy doanh nghiệp tương ứng với mã mời
→ Đăng ký thành công, người dùng thuộc doanh nghiệp đó

Ghi chú:
- Giữ nguyên logic đăng ký bằng mã mời hiện tại
- Không bị ảnh hưởng bởi cấu hình doanh nghiệp mặc định của AppId

---

### 5.3 注册场景二：未填写邀请码
处理逻辑：
用户注册（未填写邀请码）
→ 根据 AppId 查询默认企业
→ 查询成功：注册成功，归属默认企业
→ 查询失败：注册失败

失败提示示例：
当前应用未配置默认企业，无法完成注册

---

### 5.3 Trường hợp 2: Đăng ký không có mã mời
Luồng xử lý:
Người dùng đăng ký (không nhập mã mời)
→ Truy vấn doanh nghiệp mặc định theo AppId
→ Thành công: đăng ký thành công, thuộc doanh nghiệp mặc định
→ Thất bại: đăng ký không thành công

Thông báo lỗi ví dụ:
Ứng dụng hiện tại chưa được cấu hình doanh nghiệp mặc định, không thể hoàn tất đăng ký

---

## 六、异常与限制

| 场景 | 处理方式 |
| ---- | ---- |
| AppId 未配置默认企业 | 禁止无邀请码注册 |
| AppId 被停用 | 禁止注册 |
| 邀请码无效 | 注册失败 |

---

## 6. Trường hợp ngoại lệ và hạn chế

| Trường hợp | Cách xử lý |
| ---- | ---- |
| AppId chưa cấu hình doanh nghiệp mặc định | Không cho phép đăng ký không có mã mời |
| AppId bị vô hiệu hóa | Không cho phép đăng ký |
| Mã mời không hợp lệ | Đăng ký thất bại |

---

## 七、验收标准
- 填写邀请码时，用户正确归属至邀请码企业
- 未填写邀请码时，用户正确归属至 AppId 默认企业
- AppId 未配置默认企业时，注册被拒绝
- AppId 停用后无法继续注册

---

## 7. Tiêu chí nghiệm thu
- Khi nhập mã mời, người dùng được gán đúng doanh nghiệp
- Khi không nhập mã mời, người dùng được gán vào doanh nghiệp mặc định theo AppId
- Khi AppId chưa cấu hình doanh nghiệp mặc định, đăng ký bị từ chối
- Khi AppId bị vô hiệu hóa, không thể tiếp tục đăng ký
