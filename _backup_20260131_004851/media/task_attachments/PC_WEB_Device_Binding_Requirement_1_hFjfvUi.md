# PC / WEB Device Binding and Login Verification Requirement
# PC / WEB 端设备绑定与登录校验需求
# Yêu cầu ràng buộc thiết bị và xác thực đăng nhập PC / WEB

---

## 一、中文（Chinese）

### 需求说明：PC / WEB 端设备绑定与登录校验

#### 1. 需求背景
为提升账号安全性，防止账号被盗用、共享或在非授权设备上登录，需在 PC 端与 WEB 端引入设备绑定机制，对登录设备进行校验控制，并支持后台统一管理设备绑定关系。

#### 2. 需求目标
- 实现 PC / WEB 端登录设备识别与绑定
- 基于设备指纹限制账号仅可在已授权设备上登录
- 支持后台解除设备绑定，保障业务灵活性
- 提升整体账号安全等级

#### 3. 需求范围

**适用端：**
- PC 客户端
- WEB 端（浏览器）

**适用对象：**
- 所有需要登录的用户账号

#### 4. 功能需求

##### 4.1 设备信息获取
1. PC / WEB 端在用户登录时需获取当前登录设备的设备信息  
2. 设备信息可由多个设备维度信息组合获取，不要求绝对硬件唯一  
3. WEB 端需单独提供设备信息获取接口，不得影响现有登录及业务接口  

##### 4.2 设备指纹生成与绑定机制
1. 客户端需基于采集到的多维设备信息生成设备指纹（Device Fingerprint）  
2. 设备指纹需具备不可逆、难以伪造及相对稳定的特性  
3. 首次登录成功后，设备指纹需与用户账号进行绑定并持久化存储  
4. 设备指纹作为后续登录校验的唯一设备凭证  

##### 4.3 设备绑定规则
1. 用户首次登录成功后自动绑定当前设备指纹  
2. 单个账号同一时间仅允许绑定一个有效设备  
3. 设备指纹需与账号建立稳定绑定关系  

##### 4.4 登录校验规则
1. 登录时需提交当前设备指纹  
2. 服务端校验设备指纹是否与已绑定设备一致  
3. 校验结果：  
   - 一致：允许登录  
   - 不一致：拒绝登录，并提示“当前设备未授权，已限制登录”  

##### 4.5 后台设备管理
1. 后台支持查看账号已绑定设备信息（脱敏展示）  
2. 支持手动解除账号与设备的绑定  
3. 解绑后原设备立即失效，新设备可重新登录并绑定  

#### 5. 安全与接口要求
- 设备指纹相关接口需进行加密或签名处理  
- 接口需支持时间戳、防重放机制  
- 服务端需校验设备指纹合法性，防止伪造或篡改  
- WEB 端设备接口需与原有接口逻辑解耦  

#### 6. 异常与边界说明
- 本需求不承诺绝对设备唯一性  
- 在设备更换、系统重装等场景下，可通过后台解绑处理  
- 若检测到设备指纹异常或校验失败，默认拒绝登录  

#### 7. 验收标准
- 已绑定设备可正常登录  
- 非绑定设备无法登录  
- 后台解绑后可重新绑定新设备  
- 不影响现有功能  

---

## II. English

### Requirement: PC / WEB Device Binding and Login Verification

#### 1. Background
To enhance account security and prevent account theft, sharing, or access from unauthorized devices, a device binding mechanism shall be introduced for PC and WEB platforms, with centralized device management via the admin console.

#### 2. Objectives
- Identify and bind login devices on PC / WEB
- Restrict account access to authorized devices using device fingerprints
- Allow device unbinding through the backend
- Improve overall account security

#### 3. Scope

**Platforms:**
- PC Client
- Web Browser

**Users:**
- All user accounts requiring login

#### 4. Functional Requirements

##### 4.1 Device Information Collection
1. Device information must be collected during login on PC / WEB  
2. Device identification is generated from multiple attributes, not relying on absolute hardware uniqueness  
3. WEB must provide a dedicated device information API without affecting existing interfaces  

##### 4.2 Device Fingerprint Generation and Binding
1. Generate a device fingerprint based on multiple device attributes  
2. The fingerprint must be non-reversible, hard to forge, and relatively stable  
3. Bind the fingerprint to the user account upon first successful login  
4. Use the fingerprint as the sole credential for device verification  

##### 4.3 Device Binding Rules
1. Automatically bind the current device on first login  
2. Only one active device is allowed per account at a time  
3. Maintain a stable binding relationship  

##### 4.4 Login Verification
1. Submit the device fingerprint during login  
2. Verify whether the fingerprint matches the bound device  
3. Results:  
   - Match: login allowed  
   - Mismatch: login denied with message “This device is not authorized”  

##### 4.5 Backend Device Management
1. View bound device information (masked)  
2. Manually unbind devices  
3. After unbinding, the old device becomes invalid and a new device may bind  

#### 5. Security & API Requirements
- Encrypt or sign device-related APIs  
- Support timestamp and anti-replay mechanisms  
- Validate fingerprint authenticity on the server  
- WEB APIs must be decoupled from existing logic  

#### 6. Exceptions & Boundaries
- Absolute device uniqueness is not guaranteed  
- Device replacement can be handled via unbinding  
- Login is denied by default if verification fails  

#### 7. Acceptance Criteria
- Authorized devices can log in  
- Unauthorized devices are blocked  
- Devices can be rebound after unbinding  
- Existing functionality remains unaffected  

---

## III. Tiếng Việt (Vietnamese)

### Yêu cầu: Ràng buộc thiết bị và xác thực đăng nhập PC / WEB

#### 1. Bối cảnh
Nhằm nâng cao bảo mật tài khoản, ngăn chặn việc chia sẻ, đánh cắp hoặc đăng nhập từ thiết bị không được phép, hệ thống cần triển khai cơ chế ràng buộc thiết bị cho PC và WEB, đồng thời hỗ trợ quản lý tập trung qua trang quản trị.

#### 2. Mục tiêu
- Nhận diện và ràng buộc thiết bị đăng nhập PC / WEB  
- Chỉ cho phép đăng nhập từ thiết bị đã được ủy quyền dựa trên dấu vân tay thiết bị  
- Hỗ trợ quản trị viên hủy ràng buộc thiết bị  
- Nâng cao mức độ an toàn tài khoản  

#### 3. Phạm vi

**Nền tảng:**
- Ứng dụng PC  
- Trình duyệt WEB  

**Đối tượng:**
- Tất cả tài khoản người dùng  

#### 4. Yêu cầu chức năng

##### 4.1 Thu thập thông tin thiết bị
1. Thu thập thông tin thiết bị khi đăng nhập trên PC / WEB  
2. Nhận diện thiết bị dựa trên nhiều thuộc tính, không yêu cầu phần cứng duy nhất tuyệt đối  
3. WEB cần cung cấp API thu thập thiết bị riêng, không ảnh hưởng hệ thống hiện tại  

##### 4.2 Tạo và ràng buộc dấu vân tay thiết bị
1. Tạo dấu vân tay thiết bị dựa trên nhiều thông tin thiết bị  
2. Dấu vân tay phải khó giả mạo, không thể đảo ngược và tương đối ổn định  
3. Ràng buộc dấu vân tay với tài khoản khi đăng nhập thành công lần đầu  
4. Dấu vân tay được dùng để xác thực đăng nhập về sau  

##### 4.3 Quy tắc ràng buộc thiết bị
1. Tự động ràng buộc thiết bị hiện tại khi đăng nhập lần đầu  
2. Mỗi tài khoản chỉ có một thiết bị hoạt động tại cùng thời điểm  
3. Quan hệ ràng buộc phải ổn định  

##### 4.4 Xác thực đăng nhập
1. Gửi dấu vân tay thiết bị khi đăng nhập  
2. Máy chủ xác thực dấu vân tay với thiết bị đã ràng buộc  
3. Kết quả:  
   - Trùng khớp: cho phép đăng nhập  
   - Không khớp: từ chối đăng nhập với thông báo “Thiết bị chưa được ủy quyền”  

##### 4.5 Quản lý thiết bị phía quản trị
1. Quản trị viên có thể xem thiết bị đã ràng buộc (ẩn thông tin nhạy cảm)  
2. Hỗ trợ hủy ràng buộc thiết bị thủ công  
3. Sau khi hủy, thiết bị cũ mất hiệu lực và có thể ràng buộc thiết bị mới  

#### 5. Yêu cầu bảo mật & API
- API liên quan phải được mã hóa hoặc ký số  
- Hỗ trợ timestamp và chống replay  
- Máy chủ xác thực tính hợp lệ của dấu vân tay  
- API WEB phải tách biệt với logic cũ  

#### 6. Ngoại lệ & giới hạn
- Không đảm bảo thiết bị là duy nhất tuyệt đối  
- Có thể xử lý đổi thiết bị qua hủy ràng buộc  
- Mặc định từ chối đăng nhập nếu xác thực thất bại  

#### 7. Tiêu chí nghiệm thu
- Thiết bị hợp lệ đăng nhập được  
- Thiết bị không hợp lệ bị chặn  
- Có thể ràng buộc lại sau khi hủy  
- Không ảnh hưởng chức năng hiện có  
