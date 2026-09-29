# Digital Twin cho quản lý nhiệt độ

**Tác giả:** Dang Minh Hoang

**Lớp:** Project Course Digital Twin, Kỳ Hè 2026

---

## Abstract

Báo cáo này mô tả khái niệm, phương pháp luận và kiến trúc phần mềm của một *digital twin* (Digital Twin) cho dự đoán nhiệt độ trên một thiết bị levitator điện động động (electrodynamic levitator) theo tiêu chuẩn TEAM-28 (COMPUMAG). Thay vì sử dụng phần mềm CAE thương mại, đã chọn một bộ giải Python tự phát triển, vì mục tiêu thực tế không phải một lần mô phỏng, mà là một *mô hình dự đoán thời gian thực* (real-time prediction model) chạy trên một thiết bị di động thông qua Augmented Reality. Báo cáo này giải thích lựa chọn này dựa trên vật lý (các tổn hao Joule có tỷ lệ bình phương với dòng điện trong khi phân bố không gian cố định, cho phép một lần giải FEM ngoại tuyến cộng với một Reduced-Order-Model thời gian thực), và tóm tắt các kết quả hiện tại cũng như kết quả dự kiến. Để triển khai mô hình vật lý, đã sử dụng một công cụ AI được tích hợp vào môi trường phát triển, trong đó tất cả các giả định vật lý và tiêu chí xác nhận đã được nhóm định nghĩa và kiểm tra. Những câu hỏi mở và những hạn chế của mô hình hiện tại được trình bày một cách minh bạch.

---

## I. Giới thiệu

### Vấn đề cần giải quyết

Bài toán TEAM-28 là một tiêu chuẩn được chứng nhận trong cộng đồng Computational Electromagnetics (COMPUMAG) để xác nhận các bộ giải điện từ tự viết: Một đĩa nhôm dẫn điện levitate trên một cách bố trí cuộn dây được điều khiển bởi dòng điện xoay chiều ($I_{\mathrm{rms}}\approx5\,\mathrm{A}$ đo được, $f=50\,\mathrm{Hz}$). Thông lượng từ biến đổi theo thời gian cảm ứng các dòng xoáy trong đĩa, tạo ra cả lực nâng (Levitation) và tổn hao nhiệt. Thiết bị thử nghiệm được xây dựng tại khoa tương ứng với tiêu chuẩn này về cơ bản, nhưng có thêm một lõi ferromagnetic ($\mu_r\approx1000$) và một vòng ngoài ferromagnetic, những thứ không xuất hiện trong bài toán gốc và tự sinh ra một lượng nhiệt đáng kể.

### Từ mô hình mô phỏng đến Digital Twin

Nhiệm vụ không phải là tính *một lần* trường nhiệt độ, mà là xây dựng một mô hình (i) dự đoán trường nhiệt độ $T(r,z,t)$ **liên tục** khi dòng điện hoạt động thay đổi theo thời gian thực, (ii) **xác nhận** với thiết bị thử nghiệm thực (camera IR, cặp nhiệt điện), và (iii) cuối cùng có thể xem qua **QR code** trên điện thoại thông minh trong Augmented Reality. Ba yêu cầu này cùng nhau định nghĩa một *digital twin* theo đúng nghĩa của nó và là điểm xuất phát của tất cả các quyết định phương pháp được giải thích dưới đây.

---

## II. Khái niệm vật lý cơ bản: Tại sao thời gian thực là có thể

Một digital twin sẽ tính toán lại một mô phỏng FEM đầy đủ mỗi khi dòng điện thay đổi, điều này sẽ không thể thực hiện được trên điện thoại thông minh (thời gian tính toán: từ vài giây đến vài phút cho mỗi lần chạy). Giải pháp nằm ở một quan sát vật lý, không phải một lối tắt phần mềm: Với tần số cố định ($50\,\mathrm{Hz}$) và các tính chất vật liệu tuyến tính, tất cả các tổn hao Joule có tỷ lệ bình phương với dòng điện ($P\propto I^2$), trong khi **phân bố không gian** của các tổn hao *không* thay đổi -- chỉ biên độ của chúng thay đổi. Từ đây suy ra một kiến trúc hai giai đoạn:

1. **Ngoại tuyến (một lần):** Giải FEM điện từ một lần ở một dòng điện tham chiếu $I_{\mathrm{ref}}$ và cung cấp một bản đồ tổn hao phân giải theo không gian $\hat q_{\mathrm{Al}}(r,z)$ cũng như các tổn hao cuộn dây $\hat P_{\mathrm{Cu}}$.

2. **Trực tuyến (Mili giây):** Đối với một dòng điện bất kỳ $I$ và nhiệt độ vật thể được biết cuối cùng $\bar T$, các đại lượng này chỉ được nhân với vô hướng.

Điều quan trọng là hiệu chỉnh $\sigma(T)$ cho hai vật thể có **chiều ngược nhau** (xem Phần III): tổn hao dòng xoáy của đĩa $\propto\sigma_{\mathrm{Al}}$, còn tổn hao ohm của cuộn dây $\propto1/\sigma_{\mathrm{Cu}}$. Do đó các phương trình thời gian thực là

$$q_{\mathrm{Al}}(r,z;I,\bar T) = \hat q_{\mathrm{Al}}(r,z)\left(\frac{I}{I_{\mathrm{ref}}}\right)^{\!2}\frac{\sigma_{\mathrm{Al}}(\bar T)}{\sigma_{\mathrm{Al}}(T_{\mathrm{ref}})} \qquad (1)$$

$$P_{\mathrm{Cu}}(I,\bar T) = \hat P_{\mathrm{Cu}}\left(\frac{I}{I_{\mathrm{ref}}}\right)^{\!2}\frac{\sigma_{\mathrm{Cu}}(T_{\mathrm{ref}})}{\sigma_{\mathrm{Cu}}(\bar T)} \qquad (2)$$

Cả hai cấp nguồn cho một mô hình nhiệt giảm bậc (ROM), cũng chỉ hoạt động với số học vectơ/vô hướng.

> **Ghi chú 1 (Tình trạng triển khai).** Phương trình (1) đã được triển khai đầy đủ trong mô hình thời gian thực. Phương trình (2) thì **chưa**: các nút cuộn dây và lõi sắt khi chạy chỉ được nhân với $(I/I_{\mathrm{ref}})^2$. Sự phụ thuộc nhiệt độ của cuộn dây thay vào đó nằm ẩn trong các hệ số dẫn nhiệt đối lưu $hA$ đã được fit với dữ liệu đo (Phần VI). Tại điểm hiệu chỉnh điều này là chính xác; với các điểm vận hành xa nó, đây là một đơn giản hóa đã biết.

Sự phân tách này là lõi phương pháp của dự án: "Thông minh" nằm hoàn toàn trong bộ giải ngoại tuyến một lần; khả năng thời gian thực xuất phát từ cấu trúc vật lý của bài toán (tuyến tính, tần số cố định), không phải từ vật lý đơn giản hóa.

---

## III. Mô hình vật lý

Mô hình bao gồm ba bài toán con được kết hợp và có tính đối xứng trục, được giải trong 2D $(r,z)$ và xoay để hiển thị thành 3D. Phép trình bày đầy đủ nằm ở Phụ lục A.

**Điện từ (Phasor):** Vì chỉ có tổn hao nhiệt được tính trung bình theo chu kỳ là liên quan đến (so với $50\,\mathrm{Hz}$ chậm) nhiệt động, trường không được mô phỏng từng bước thời gian, mà được giải như một phasor phức tạp $A_\varphi(r,z)$ -- công thức sử dụng ở đây dựa trên thế vectơ từ theo công trình cổ điển của Bíró và Preis,

$$-\nabla\!\cdot\!\left(\nu\nabla A_\varphi\right) + \nu\frac{A_\varphi}{r^{2}} + j\omega\sigma A_\varphi = J_s$$

với $\nu=1/(\mu_r\mu_0)$, $\omega=2\pi f$ và mật độ dòng điện tích (đã cho) $J_s$ trong các cuộn dây (cuộn trong/ngoài có hướng quấn ngược chiều nhau). Trong lõi/vòng ferromagnetic, $\nu$ giảm đáng kể và do đó tập hợp thông lượng.

**Tổn hao nhiệt Joule:** Từ mật độ dòng xoáy cảm ứng $J_e=-j\omega\sigma A_\varphi$ suy ra mật độ tổn hao được tính trung bình theo chu kỳ

$$q(r,z) = \frac{|J_e|^{2}}{2\sigma} = \tfrac12\,\sigma\,\omega^{2}\,|A_\varphi|^{2}\ \;[\mathrm{W/m^3}]$$

sự phụ thuộc bình phương của nó vào $|A_\varphi|$ là cơ sở của việc mở rộng quy mô $I^2$ từ phương trình trên.

**Độ dẫn điện phụ thuộc vào nhiệt độ:** Vì sự gia tăng $70\,\mathrm K$ thay đổi điện trở riêng khoảng $\approx27\,\%$, chúng ta có $\sigma(T)=\sigma_0/(1+\alpha(T-T_0))$ với $\alpha\approx3{,}9\times10^{-3}\,\mathrm{K^{-1}}$ -- với tác dụng ngược chiều: Tổn hao đĩa $\propto\sigma_{\mathrm{Al}}$ (phản hồi âm), Tổn hao cuộn dây $\propto1/\sigma_{\mathrm{Cu}}$ (phản hồi dương). Cả hai tác dụng chỉ thay đổi biên độ, do đó kiến trúc hai giai đoạn vẫn hợp lệ.

**Truyền dẫn nhiệt:** Mật độ tổn hao $q$ cấp nguồn cho phương trình Fourier không ổn định

$$\rho c_p\,\frac{\partial T}{\partial t} = \nabla\!\cdot\!(k\nabla T) + q$$

với điều kiện biên Robin $-k\,\partial T/\partial n=h(T-T_\infty)$. Trong trường hợp ổn định, cân bằng năng lượng $\int_V q\,\mathrm dV=\oint_\Gamma h(T-T_\infty)\,\mathrm dA$ phải được thỏa mãn chính xác -- bài kiểm tra xác nhận trung tâm của bộ giải nhiệt (xem Phần V).

---

## IV. Triển khai số học và Kiến trúc phần mềm

Cả hai bài toán con được rời rạc hóa bằng Phương pháp phần tử hữu hạn (Finite Element Method - FEM) trong công thức Galerkin, với các phần tử tam giác tuyến tính (P1) trên một lưới 2D có cấu trúc $(r,z)$; dạng yếu có tính đối xứng trục mang trọng số thể tích $2\pi r$ (chi tiết ở Phụ lục A). Việc lắp ráp (assembly) ma trận điện từ tạo ra một ma trận thưa phức tạp (vì $j\omega\sigma$), được giải bằng `scipy.sparse.linalg.spsolve` dựa trên NumPy và SciPy. Với $\sim\!10^4$ ẩn số (2D, đối xứng trục) một bộ giải trực tiếp là đủ; độ sâu da trong nhôm ở $50\,\mathrm{Hz}$ ($\delta\approx12\,\mathrm{mm}\gg3\,\mathrm{mm}$ độ dày đĩa) làm cho lưới mịn trong hướng $z$ là không cần thiết.

Từ giải FEM một lần, một mô hình chiều thấp có khả năng thời gian thực được bắt nguồn: tỷ lệ $I^2$ với hằng số thời gian bậc nhất ($\tau\approx4{,}07\,\mathrm{min}$ tại $R=80\,\mathrm{mm}$) cho đĩa, cũng như một mạng RC phân bố (*lumped-parameter thermal network*) cho cuộn dây, lõi sắt/vòng ngoài, và nút khí chung -- một nguyên lý mô hình hóa được thiết lập trong kỹ thuật điều khiển điện, có thể được hiệu chỉnh trực tiếp từ dữ liệu cảm biến thực tế. Toàn bộ bước trực tuyến giảm xuống thành số học $O(n)$, chạy được trong vài mili giây trong trình duyệt của một điện thoại thông minh.

**Hình 1: Đường ống phần mềm** (mô tả thay vì TikZ)

Đường ống phần mềm chảy từ trái sang phải:
- `params.yaml` (nguồn chân lý duy nhất cho tất cả các tham số)
- `config.py` (nạp/chuẩn hóa đơn vị, tính $I_{\mathrm{peak}}$)
- `em_solver.py` (giải FEM điện từ phasor, tính bản đồ tổn hao)
- `thermal_solver.py` (giải FEM nhiệt, kiểm tra cân bằng năng lượng)
- `rom.py` / `twin_core.py` (ROM thời gian thực - đây là SSOT cho tích phân)
- `build_twin_html_fem.py` (bake thành `digital_twin_fem.html` cho AR + QR)

Đường cảm biến riêng biệt:
- `data_io.py` + Arduino (cầu nối cảm biến serieel/giả) → hiệu chỉnh ROM

Xác nhận chéo bổ sung:
- `xval_twin.py` (đảm bảo bộ tích phân JavaScript được bake khớp với bộ tích phân tham chiếu Python đến $10^{-9}$ tuyệt đối)

Hình 1 cho thấy đường ống một chiều: Mỗi tệp có chính xác một trách nhiệm, và tất cả các tham số vật lý nằm ở trung tâm trong `params.yaml` (*single source of truth*) -- không có hằng số nào được kết dây cứng trong mã.

---

## V. Tại sao không dùng công cụ CAE thương mại

Các công cụ như SimScale, COMSOL/ANSYS Maxwell hoặc FEMM có thể giải quyết bài toán con điện từ-nhiệt về cơ bản -- COMSOL thậm chí còn cung cấp một mô hình ví dụ hoàn chỉnh cho TEAM 28 --, tương tự như các bộ giải mã nguồn mở Elmer và FEniCS. Tuy nhiên, không ai trong số đó đáp ứng yêu cầu thực tế -- một mô hình có khả năng thời gian thực, có thể hiệu chỉnh bằng cảm biến, chạy được trên điện thoại thông minh (Bảng 1).

| Tiêu chí | SimScale | COMSOL/Maxwell | FEMM | Elmer/FEniCS | **Python (đã chọn)** |
|---|---|---|---|---|---|
| EM tần số thấp (Dòng xoáy) | giới hạn | ✓ | ✓ | ✓ | ✓ (đã xác minh đường tổn hao; lực nâng còn bỏ ngỏ, xem Phần VIII) |
| Ghép EM→Nhiệt | khó khăn | ✓ | yếu | phức tạp | ✓ trực tiếp trong bộ nhớ |
| ROM / Khả năng thời gian thực | -- | một phần, tốn kém | -- | -- | ✓ **Thiết kế lõi** |
| Xuất sang Web/AR | -- | -- | -- | -- | ✓ 1 tệp HTML |
| Hiệu chỉnh cảm biến | -- | độc quyền | -- | tự xây dựng | ✓ `data_io.py` |
| Chạy trên macOS | ✓ | ✓ (tốn kém) | -- chỉ Windows | ✓ | ✓ |
| Chi phí | Giới hạn Core-Hour | hàng ngàn € | miễn phí | miễn phí | miễn phí |
| Hộp đen? | có | có | một phần | không | **không -- kiểm soát đầy đủ** |

Điểm quyết định có tính cấu trúc: Các gói FEM thương mại và nhiều gói mã nguồn mở đóng gói bộ giải như một hộp đen -- mỗi thay đổi dòng điện đòi hỏi một khởi động lại bộ giải hoàn toàn. Để tận dụng cấu trúc $I^2$ từ Phần II (giải FEM một lần, sau đó chỉ mở rộng quy mô), bộ giải phải được kiểm soát ở cấp mã nguồn: Bản đồ tổn hao $\hat q(r,z)$ *trước khi* nhân với $I^2$ phải được trích xuất một cách có mục đích và sử dụng lại. FEMM cũng được loại trừ vì một lý do thực tế (chỉ Windows gốc, máy phát triển là macOS).

---

## VI. Xác nhận và các kết quả hiện tại

| Nguồn tổn hao | $P$\,[W] |
|---|---|
| Tổn hao dòng xoáy đĩa (Al) | 25,81 |
| Tổn hao dòng xoáy lõi sắt + vòng ngoài | 5,86 |
| Tổn hao cuộn dây ohm (trong 52,32 + ngoài 54,12) | 106,44 |
| **Tổng cộng** | **138,11** |

*(Bảng: tổn hao của FEM offline tại **biên độ** kích thích 5 A và $T_\infty=20\,^\circ$C. Xem Ghi chú 3 để quy đổi sang điểm vận hành thực.)*

Bảng trên cho thấy phân bố tổn hao hiện tại. Các kiểm tra nội bộ dưới đây được chạy lại mỗi khi mô hình thay đổi; **mức độ giá trị chứng minh của chúng có chủ ý khác nhau**:

- **Cân bằng năng lượng: sai lệch $0{,}000\,\%$.** Tại điểm ổn định, $\int_V q\,\mathrm dV = \oint_\Gamma h(T-T_\infty)\,\mathrm dA$. Đây là phép kiểm tra *có giá trị nhất*, vì nó đối chiếu các số hạng thể tích và số hạng biên vốn được lắp ráp độc lập với nhau.
- **Kích thước miền: mọi sai lệch $<1\,\%$** (lớn nhất: $P_{\mathrm{đĩa}}$ với $0{,}767\,\%$) khi so sánh điều kiện biên Dirichlet với Neumann trên miền $1\times1\,\mathrm m$ — đúng phép chứng minh mà khoa yêu cầu, rằng biên ngoài đã đủ xa.
- **Tỷ lệ $I^2$: $P(2I)/P(I) = 3{,}994$** (giá trị lý thuyết $4{,}000$) khi giải lại **toàn bộ** FEM. Sai lệch còn lại $0{,}15\,\%$ *không phải* lỗi, mà là hệ quả dự kiến của hiệu chỉnh phi tuyến $\mu_r(B)$: khi dòng tăng gấp đôi, $\mu_r$ trong sắt giảm từ $993$ xuống $977$, nên tổn hao tăng hơi dưới mức bình phương.
- **Xác nhận chéo: $<10^{-9}$ (tuyệt đối)** giữa bộ tích phân thời gian thực được bake bằng JavaScript và bộ tích phân tham chiếu Python (`xval_twin.py`), kiểm tra trên bảy kịch bản dòng điện.

> **Ghi chú 2 (Phép kiểm tra $I^2$ trong ROM).** Bản thân ROM cho kết quả đúng bằng $4{,}000000$ với cùng phép kiểm tra này. Tuy nhiên giá trị đó **mang tính vòng tròn**: ROM *chính là* một phép nhân vô hướng với $(I/I_{\mathrm{ref}})^2$ theo định nghĩa, nên nó không thể trượt bài kiểm tra này. Nó chỉ chứng minh số học của phép giảm bậc là đúng, chứ không chứng minh vật lý. Con số có giá trị chứng minh là $3{,}994$ từ FEM ở trên.

> **Ghi chú 3 (Quy ước dòng điện).** Giá trị đo tại thiết bị $I_{\mathrm{rms}}=5\,\mathrm A$ là **giá trị hiệu dụng**; biên độ tương ứng là $\hat I=\sqrt2\,I_{\mathrm{rms}}=7{,}07\,\mathrm A$. Chuỗi tính tổn hao (bảng trên) có chủ ý đưa $5\,\mathrm A$ vào làm **biên độ phasor**. Vì mọi tổn hao đều $\propto I^2$, các giá trị công suất trong bảng do đó **thấp hơn 2 lần** so với công suất thực sự tiêu tán tại điểm vận hành thật. Điều này được chấp nhận và có chủ đích, vì hệ số hằng số này được hấp thụ hoàn toàn khi fit các hệ số $hA$ với nhiệt độ cuộn dây đo được — nhờ vậy dự đoán **nhiệt độ** vẫn đúng. Ngược lại, chuỗi tính **lực** dùng biên độ thật $\hat I$, vì một lực thì không thể "hiệu chỉnh cho mất đi" được.

Biên an toàn chống bão hòa của sắt cũng không đáng lo, nhưng **phải được so sánh đúng cách**: bộ giải báo $B_{\max}=0{,}663\,\mathrm T$ dưới dạng **giá trị hiệu dụng**, trong khi $B_{\mathrm{sat}}=1{,}5\,\mathrm T$ là một đại lượng vật liệu dạng **giá trị đỉnh**. Giá trị đỉnh cần dùng để so sánh vì thế là $\sqrt2\cdot0{,}663\approx0{,}94\,\mathrm T$, tức khoảng $63\,\%$ của $B_{\mathrm{sat}}$. Giả định $\mu_r$ tuyến tính vẫn hợp lệ, nhưng biên an toàn nhỏ hơn so với những gì một phép so sánh trực tiếp hai giá trị hiệu dụng gợi ra.

Hai điểm hoạt động thực tế đã được đo lường bằng camera IR ($190\,\mathrm V\to5\,\mathrm A$ làm điểm hoạt động chính, $270\,\mathrm V\to7{,}8\,\mathrm A$ làm cơ sở hiệu chỉnh). Mô hình mạng RC của các cuộn dây được hiệu chỉnh trực tiếp so với tích phân thời gian đầy đủ, phi tuyến tính và đạt chính xác trạng thái ổn định ($T_{\mathrm{trong}}=79{,}00\,^\circ$C, $T_{\mathrm{ngoài}}=74{,}00\,^\circ$C tại $7{,}8\,\mathrm A$). Chỉ các cuộn dây được sơn tối cung cấp các giá trị IR đáng tin cậy (độ phát xạ không xác định của nhôm trần); việc xác nhận đĩa và lõi là nhiệm vụ của cảm biến tiếp xúc được lên kế hoạch.

Đường dẫn hiệu chỉnh phía phần mềm (`arduino/thermal_sensor.ino` → `data_io.py` → `rom.calibrate_UA()`) được triển khai hoàn toàn và được kiểm tra thông suốt với dữ liệu đo lường tổng hợp; chỉ thiếu việc xây dựng cảm biến thực tế (xem Phụ lục C).

---

## VII. Kết quả dự kiến và Triển vọng

Dự kiến ngắn hạn: một digital twin được hiệu chỉnh hoàn toàn với khả năng thời gian thực với nhiệt độ cuộn dây gần như thực (đã đạt được, sai số RMS $\approx2{,}5$--$3\,^\circ$C); một đường cong gia nhiệt *và* làm lạnh thực tế, làm cho mạng RC trước đây thiếu xác định (đặc biệt là nút khí chung) hoàn toàn có thể xác định; một phép đo tiếp xúc đáng tin cậy của phía dưới đĩa; và một khung nhìn AR được xuất bản có QR code, có thể gọi mà không cần cài đặt. Trung hạn: một bảng hiệu chỉnh dày đặc hơn từ góc xoay của tay cầm → dòng điện, một thiết bị đo dòng điện thực tế cho một dạng thời gian $I(t)$ được đo lường, và một xác định đáng tin cậy hơn về độ thẩm thấu từ sắt để làm rõ câu hỏi mở được đề cập trong Phần VIII.

---

## VIII. Câu hỏi mở và Giới hạn

Theo tinh thần minh bạch khoa học: Chiều cao levitation dự đoán ($z_{\mathrm{eq}}\approx11{,}7$--$14{,}7\,\mathrm{mm}$) không phù hợp với khe quan sát ($7$--$8\,\mathrm{mm}$); bão hòa từ đã được loại trừ như một nguyên nhân (thay đổi lực $<0{,}1\,\%$), nguyên nhân có khả năng nhất là giá trị $\mu_r$ đặt chỗ chưa được đo của sắt. Một phù hợp ngược lại tùy ý về $\mu_r$ với chiều cao quan sát được *không được* thực hiện một cách có chủ ý. Tiêu chuẩn TEAM-28 gốc (không có sắt, $20\,\mathrm A$) cũng sai lệch $\approx28\,\%$ so với bảng tham chiếu -- tạm dừng, không chặn. Mà không có đường cong làm lạnh thực tế, nút khí chung của mạng RC vẫn thiếu xác định. Cũng còn bỏ ngỏ: trong mô hình, đĩa và cuộn dây đạt nhiệt độ gần như bằng nhau, trong khi dữ liệu IR gợi ý cuộn dây phải nóng hơn rõ rệt; muốn kết luận cần cặp nhiệt điện gắn ở mặt dưới đĩa còn thiếu. Cuối cùng, phản hồi $\sigma(T)$ của cuộn dây hiện chỉ được chứa ngầm qua phép fit $hA$ (Ghi chú 1).

---

## IX. Kết luận

Dự án theo một con đường có cơ sở vật lý để tạo ra một digital twin có khả năng thời gian thực: Một giải FEM một lần, độ phân giải cao được giảm xuống thành thời gian chạy mili giây thông qua tỷ lệ $I^2$ và một Reduced-Order-Model có thể hiệu chỉnh -- một cấu trúc không thể được nhận ra bằng các công cụ CAE thương mại được đóng gói. Mỗi thay đổi đối với mô hình được phát hành độc quyền thông qua các tiêu chí vật lý khó, được tự động hóa (cân bằng năng lượng, nhất quán $I^2$, xác nhận chéo, so sánh với dữ liệu cảm biến thực tế). Kết quả hiệu chỉnh đầu tiên về nhiệt độ cuộn dây xác nhận khả năng nâng cao của mô hình; chiều cao levitation vẫn tồn tại như một câu hỏi vật lý mở và sẽ được điều tra thêm bằng phần cứng cảm biến được lên kế hoạch.

---

## Phụ lục A: Phép trình bày hoàn chỉnh của các phương trình vật lý

Dạng yếu đối xứng trục của phương trình truyền dẫn nhiệt với trọng số thể tích $2\pi r$ là

$$\int k\,\nabla T\!\cdot\!\nabla v \cdot 2\pi r \,\mathrm dA + \oint_\Gamma h\,T\,v\cdot 2\pi r\,\mathrm ds = \int p\,v\cdot 2\pi r\,\mathrm dA + \oint_\Gamma h\,T_\infty\,v\cdot 2\pi r\,\mathrm ds$$

Đối với các phần tử P1, $\nabla T$ không đổi từng phần tử, do đó ma trận độ cứng phần tử $K_e = 2\pi k\,(bb^\top+cc^\top)\,A\,r_c$ suy ra trực tiếp từ các gradient hàm hình dáng $b,c$, diện tích phần tử $A$ và bán kính trọng tâm $r_c$. Ma trận biên tích phân không khí với trọng số bán kính tuyến tính kết quả từ

$$K_{\mathrm{edge}} = 2\pi h\,\tfrac{L}{12}\left(\begin{smallmatrix} 3r_a+r_b & r_a+r_b \\ r_a+r_b & r_a+3r_b\end{smallmatrix}\right)$$

Trục $r=0$ là một điều kiện đối xứng (điều kiện biên tự nhiên, không được ép buộc). Đối với bài toán con điện từ, tương tự như vậy ta có một ma trận độ cứng suy ra từ phương trình EM. Số hạng $j\omega\sigma$ làm cho ma trận này có giá trị phức; nó được lắp ráp thành **một** ma trận phức duy nhất và được phân tích trực tiếp bằng số học phức (không tách thành hệ phần thực và hệ phần ảo). Mật độ thông lượng từ suy ra từ $B_r=-\partial A_\varphi/\partial z$, $B_z=\tfrac1r\,\partial(rA_\varphi)/\partial r$.

Về mặt vật lý, phương trình (1) mô tả trường AC: Số hạng $j\omega\sigma A_\varphi$ là phản ứng dòng xoáy trong mỗi vật thể dẫn điện (đĩa, sắt); số hạng $\nu A_\varphi/r^2$ là hiệu ứng hình học của tính đối xứng trục và là lý do tại sao 2D thay vì 3D là đủ. Tại $I_{\mathrm{rms}}=5\,\mathrm A$ qua cuộn dây trong 1000 vòng, $B_{\max}$ trong lõi sắt là $0{,}663\,\mathrm T$ dưới dạng giá trị hiệu dụng, tương ứng giá trị đỉnh $\approx0{,}94\,\mathrm T$ — so với $B_{\mathrm{sat}}=1{,}5\,\mathrm T$ thì vẫn chưa bão hòa (xem Phần VI).

---

## Phụ lục B: Đường ống phần mềm hoàn chỉnh

Bảng dưới đây liệt kê các mô-đun chính của đường ống một chiều từ Hình 1.

| Tệp | Chức năng |
|---|---|
| `config.py` | nạp/chuẩn hóa `params.yaml`, mm→m, $I_{\mathrm{peak}}=I_{\mathrm{rms}}\sqrt2$ |
| `em_solver.py` | FEM phasor, tổn hao dòng xoáy/ohm, lực nâng, tiêu chuẩn TEAM-28 |
| `thermal_solver.py` | FEM nhiệt đối xứng trục, cân bằng năng lượng $0{,}000\,\%$ |
| `rom.py` | ROM thời gian thực, tỷ lệ $I^2$ chính xác, $\tau\approx4{,}07\,\mathrm{min}$ |
| `twin_core.py` | Tích phân SSOT-thời gian (mạng RC, levitation), chỉ numpy/stdlib |
| `xval_twin.py` | Xác nhận chéo tích phân Python vs. JavaScript được bake |
| `build_twin_html_fem.py` | bake → `digital_twin_fem.html` (phân phối AR) |
| `data_io.py` | Cầu nối cảm biến (serieel/giả) → `rom.calibrate_UA()` |
| `refit_hA.py` | Tái hiệu chỉnh RC thông qua tích phân đầy đủ |

---

## Phụ lục C: Kế hoạch xác nhận cảm biến

Quy định của khoa: Nhóm thiết kế một giải pháp đo lường riêng (Arduino, cặp nhiệt điện/RTD, nhiệt kế hồng ngoại). Được triển khai: Hai cặp nhiệt điện Loại K (lõi/cuộn dây trong, mặt dưới đĩa) qua bộ chuyển đổi MAX31855, cùng một cảm biến dòng Hall ACS712-20A, nối vào một Arduino gửi dữ liệu CSV 1 Hz qua USB serial (`millis,T_core_degC,T_disc_degC,I_rms_A`); một nhiệt kế hồng ngoại cầm tay đóng vai trò mẫu tham chiếu. Cảm biến dòng thay thế giả định cố định $I=5\,\mathrm A$ bằng một dạng đo thực $I(t)$, qua đó giải quyết trực tiếp kênh đo dòng thời gian thực còn thiếu. Lý do cho cảm biến tiếp xúc thay vì đo lường chỉ từ IR: Hình ảnh hồng ngoại trên nhôm trần và lõi gốm không đáng tin cậy vì độ phát xạ không xác định (xác nhận trong phép đo HIKMICRO 2026-06-23); chỉ cuộn dây được sơn tối cung cấp các giá trị hồng ngoại đáng tin cậy. Thủ tục dự kiến: (1) Hoàn thành danh sách mua sắm, (2) Hiệu chỉnh firmware so với nước đá/nước sôi, (3) Ghi một lần chạy $\geq3\tau\approx20\,\mathrm{min}$ tại $190\,\mathrm V/5\,\mathrm A$, (4) `data_io.py --mode calibrate` để hiệu chỉnh lại $hA_{\mathrm{trong/ngoài}}$, (5) Ngoài ra, ghi một đường cong làm lạnh để xác định duy nhất nút khí không khí.

---

## Tài liệu tham khảo

> Lưu ý: danh sách dưới đây được chép nguyên văn (tên tác giả/tiêu đề/tạp chí giữ
> nguyên ngôn ngữ gốc theo quy ước học thuật) từ file `dt4tm_references.bib` đã
> được kiểm chứng qua tra cứu thực tế — bản dịch tự động ban đầu của mục này có
> vài chi tiết bị diễn giải sai (nhầm tên tạp chí/năm ở 3 mục), đã được sửa lại
> ở đây cho khớp với nguồn thật.

[1] International Compumag Society. *Description of TEAM Workshop Problem 28: An Electrodynamic Levitation Device*. https://www.compumag.org/jsite/images/stories/TEAM/problem28.pdf

[2] Tao, F., Zhang, H., Liu, A., & Nee, A. Y. C. (2019). Digital Twin in Industry: State-of-the-Art. *IEEE Transactions on Industrial Informatics*, 15(4), 2405–2415.

[3] Bíró, O., & Preis, K. (1989). On the Use of the Magnetic Vector Potential in the Finite-Element Analysis of Three-Dimensional Eddy Currents. *IEEE Transactions on Magnetics*, 25(4), 3145–3159.

[4] Harris, C. R., Millman, K. J., van der Walt, S. J., et al. (2020). Array Programming with NumPy. *Nature*, 585, 357–362.

[5] Virtanen, P., Gommers, R., Oliphant, T. E., et al. (2020). SciPy 1.0: Fundamental Algorithms for Scientific Computing in Python. *Nature Methods*, 17, 261–272.

[6] Meeker, D. C. (2020). *Finite Element Method Magnetics (FEMM), Version 4.2, User's Manual*. https://www.femm.info

[7] Malinen, M., & Råback, P. (2013). Elmer Finite Element Solver for Multiphysics and Multiscale Problems. Trong I. Kondov & G. Sutmann (Chủ biên), *Multiscale Modelling Methods for Applications in Materials Science* (tr. 101–113). Forschungszentrum Jülich.

[8] Langtangen, H. P., & Logg, A. (2017). *Solving PDEs in Python: The FEniCS Tutorial I*. Springer.

[9] COMSOL Multiphysics. *An Electrodynamic Levitation Device*. Application Gallery. https://www.comsol.com/model/an-electrodynamic-levitation-device-14221

[10] Wallscheid, O. (2021). Thermal Monitoring of Electric Motors: State-of-the-Art Review and Future Challenges. *IEEE Open Journal of the Industry Applications Society*, 2, 204–223.
