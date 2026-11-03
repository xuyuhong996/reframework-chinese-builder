// 直接执行生成的翻译代码，并在可用时验证实际 ImGui 的绘制与控件标识。
#include "Translation.hpp"
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>

#ifdef _WIN32
#include <windows.h>
#else
#include <sys/mman.h>
#include <unistd.h>
#endif

#ifdef REF_TEST_IMGUI
#include "imgui.h"
#include "imgui_internal.h"
#endif

using reframework::translation::translate;

void require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << '\n';
        std::exit(EXIT_FAILURE);
    }
}

void checkDictionaryAndRanges() {
    reframework::translation::startup();
    require(std::string(translate("Enable")) == "启用", "exact translation");
    const char slice[] = "EnableTrailingText";
    require(std::string(translate(slice, slice + 6)) == "启用", "bounded slice");
    require(translate(slice) == slice, "unknown text pointer");
    require(translate(slice, slice) == slice, "empty range");
    require(std::string(translate(" Enable \t")) == " 启用 \t", "whitespace");
    require(std::string(translate("Enable##original")) == "启用##original", "hidden suffix");
    require(std::string(translate("HashOnly")) == "哈希翻译", "hash fallback");
    require(std::strlen(translate("Long")) == 9000, "long translation");
}

void checkNonTerminatedPageBoundary() {
#ifdef _WIN32
    SYSTEM_INFO information{};
    GetSystemInfo(&information);
    const size_t page = information.dwPageSize;
    auto* memory = static_cast<char*>(VirtualAlloc(nullptr, page * 2, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    require(memory != nullptr, "allocate guarded pages");
    DWORD previous = 0;
    require(VirtualProtect(memory + page, page, PAGE_NOACCESS, &previous) != 0, "protect guard page");
#else
    const size_t page = static_cast<size_t>(sysconf(_SC_PAGESIZE));
    auto* memory = static_cast<char*>(mmap(nullptr, page * 2, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
    require(memory != MAP_FAILED, "allocate guarded pages");
    require(mprotect(memory + page, page, PROT_NONE) == 0, "protect guard page");
#endif
    char* text = memory + page - 6;
    std::memcpy(text, "Enable", 6);
    require(std::string(translate(text, memory + page)) == "启用", "guarded non-terminated range");
#ifdef _WIN32
    VirtualFree(memory, 0, MEM_RELEASE);
#else
    munmap(memory, page * 2);
#endif
}

#ifdef REF_TEST_IMGUI
void checkActualImGui() {
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.IniFilename = nullptr;
    io.DisplaySize = ImVec2(800, 600);
    io.DeltaTime = 1.0f / 60.0f;
    io.Fonts->AddFontDefault();
    unsigned char* pixels = nullptr;
    int width = 0, height = 0;
    io.Fonts->GetTexDataAsRGBA32(&pixels, &width, &height);
    ImGui::NewFrame();
    ImGui::Begin("Enable");
    require(std::string(ImGui::GetCurrentWindow()->Name) == "Enable", "window identity");
    const auto expectedFirst = ImGui::GetID("Enable");
    const auto expectedSecond = ImGui::GetID("Enabled");
    ImGui::Button("Enable");
    const auto actualFirst = GImGui->LastItemData.ID;
    ImGui::Button("Enabled");
    require(actualFirst == expectedFirst, "first widget identity");
    require(GImGui->LastItemData.ID == expectedSecond, "second widget identity");
    require(actualFirst != GImGui->LastItemData.ID, "same translation distinct identifiers");
    require(ImGui::CalcTextSize("Enable").x == ImGui::CalcTextSize("启用").x, "translated text measurement");
    const char slice[] = "EnableTrailingText";
    ImGui::TextUnformatted(slice, slice + 6);
    ImGui::Text("Value: %d", 7);
    ImGui::End();
    ImGui::Render();
    ImGui::DestroyContext();
}
#endif

int main() {
    checkDictionaryAndRanges();
    checkNonTerminatedPageBoundary();
#ifdef REF_TEST_IMGUI
    checkActualImGui();
#endif
    std::cout << "Native translation checks passed\n";
}
