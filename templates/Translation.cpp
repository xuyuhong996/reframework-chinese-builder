// 词库由构建脚本填充；算法本身保留为可直接阅读和编译测试的 C++ 源码。
#include "Translation.hpp"
#include <array>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <mutex>
#include <string>
#include <string_view>
#include <unordered_map>

#ifndef REF_TRANSLATION_TEST
#include <windows.h>
#include <filesystem>
#include <spdlog/spdlog.h>
#endif

const char* (*g_imgui_translate_fn)(const char*, const char*) = nullptr;
const char* (*g_imgui_translate_format_fn)(const char*) = nullptr;

namespace reframework::translation {
namespace {
    struct TextHash {
        using is_transparent = void;
        size_t operator()(std::string_view text) const noexcept {
            return std::hash<std::string_view>{}(text);
        }
    };
    using Dictionary = std::unordered_map<std::string, std::string, TextHash, std::equal_to<>>;
    Dictionary dictionary;
    std::unordered_map<uint32_t, std::string> hashDictionary;
    std::once_flag initialization;
    bool initialized = false;
    constexpr size_t BUFFER_COUNT = 32;
    thread_local std::array<std::string, BUFFER_COUNT> buffers;
    thread_local size_t nextBuffer = 0;

    uint32_t hashText(std::string_view text) {
        constexpr uint32_t OFFSET = 0x811c9dc5U;
        constexpr uint32_t PRIME = 0x01000193U;
        uint32_t value = OFFSET;
        for (unsigned char character : text)
            value = (value ^ character) * PRIME;
        return value;
    }

    const std::string* lookup(std::string_view text) {
        auto exact = dictionary.find(text);
        if (exact != dictionary.end())
            return &exact->second;
        auto hashed = hashDictionary.find(hashText(text));
        return hashed == hashDictionary.end() ? nullptr : &hashed->second;
    }

    std::string_view trim(std::string_view text) {
        constexpr std::string_view WHITESPACE = " \t";
        auto first = text.find_first_not_of(WHITESPACE);
        if (first == std::string_view::npos)
            return {};
        return text.substr(first, text.find_last_not_of(WHITESPACE) - first + 1);
    }

    bool translateDisplay(std::string_view text, std::string& result) {
        if (const auto* translated = lookup(text)) {
            result = *translated;
            return true;
        }
        auto clean = trim(text);
        const auto* translated = clean.empty() ? nullptr : lookup(clean);
        if (!translated)
            return false;
        const auto offset = static_cast<size_t>(clean.data() - text.data());
        result.assign(text.substr(0, offset));
        result.append(*translated);
        result.append(text.substr(offset + clean.size()));
        return true;
    }

    bool translateText(std::string_view text, std::string& result) {
        if (translateDisplay(text, result))
            return true;
        const auto marker = text.find("##");
        if (marker == std::string_view::npos || marker == 0)
            return false;
        if (!translateDisplay(text.substr(0, marker), result))
            return false;
        result.resize(result.find("##") == std::string::npos ? result.size() : result.find("##"));
        result.append(text.substr(marker));
        return true;
    }

    bool matchingFormatTokens(std::string_view original, std::string_view translated) {
        constexpr std::string_view CONVERSIONS = "%diuoxXfFeEgGaAcCsSpn";
        size_t originalPosition = 0, translatedPosition = 0;
        while (true) {
            const auto originalStart = original.find('%', originalPosition);
            const auto translatedStart = translated.find('%', translatedPosition);
            if (originalStart == std::string_view::npos || translatedStart == std::string_view::npos)
                return originalStart == translatedStart;
            const auto originalEnd = original.find_first_of(CONVERSIONS, originalStart + 1);
            const auto translatedEnd = translated.find_first_of(CONVERSIONS, translatedStart + 1);
            if (originalEnd == std::string_view::npos || translatedEnd == std::string_view::npos)
                return false;
            if (original.substr(originalStart, originalEnd - originalStart + 1) !=
                translated.substr(translatedStart, translatedEnd - translatedStart + 1))
                return false;
            originalPosition = originalEnd + 1;
            translatedPosition = translatedEnd + 1;
        }
    }

    void loadBuiltin() {
        static const std::pair<const char*, const char*> textEntries[] = {
@@TEXT_ENTRIES@@
            {nullptr, nullptr}
        };
        for (const auto& [key, value] : textEntries)
            if (key) dictionary[key] = value;
        static const std::pair<uint32_t, const char*> hashEntries[] = {
@@HASH_ENTRIES@@
            {0, nullptr}
        };
        for (const auto& [key, value] : hashEntries)
            if (value) hashDictionary[key] = value;
    }

#ifndef REF_TRANSLATION_TEST
    std::string unescape(std::string_view text) {
        std::string result;
        bool escaped = false;
        for (char character : text) {
            if (!escaped && character == '\\') { escaped = true; continue; }
            if (escaped) {
                if (character == 'n') character = '\n';
                else if (character == 'r') character = '\r';
                else if (character == 't') character = '\t';
                else if (character != '\\') result += '\\';
            }
            result += character;
            escaped = false;
        }
        if (escaped) result += '\\';
        return result;
    }

    void loadFile(const std::filesystem::path& path) {
        std::ifstream file(path, std::ios::binary);
        std::string line;
        bool firstLine = true;
        while (std::getline(file, line)) {
            if (firstLine && line.starts_with("\xEF\xBB\xBF")) line.erase(0, 3);
            firstLine = false;
            if (!line.empty() && line.back() == '\r') line.pop_back();
            if (line.empty() || line.front() == '#') continue;
            auto separator = line.find('\t');
            if (separator == std::string::npos) separator = line.find('=');
            if (separator == std::string::npos || separator == 0) continue;
            auto key = unescape(std::string_view(line).substr(0, separator));
            auto value = unescape(std::string_view(line).substr(separator + 1));
            if (!value.empty()) dictionary[key] = value;
        }
    }

    void loadExternal() {
        std::array<wchar_t, MAX_PATH> modulePath{};
        HMODULE module = nullptr;
        GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
            GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
            reinterpret_cast<LPCWSTR>(&loadExternal), &module);
        const auto length = module ? GetModuleFileNameW(module, modulePath.data(), modulePath.size()) : 0;
        if (!length || length >= modulePath.size()) return;
        const auto directory = std::filesystem::path(modulePath.data()).parent_path();
        const auto custom = directory / "reframework" / "translations.txt";
        loadFile(std::filesystem::exists(custom) ? custom : directory / "translations.txt");
    }
#endif
}

    const char* translate(const char* text, const char* textEnd) {
        if (!initialized || !text || text == textEnd)
            return text;
        try {
            const std::string_view original(text, textEnd ? static_cast<size_t>(textEnd - text) : std::strlen(text));
            std::string result;
            if (!translateText(original, result) || result == original)
                return text;
            auto& buffer = buffers[nextBuffer++ % BUFFER_COUNT];
            buffer = std::move(result);
            return buffer.c_str();
        } catch (...) {
            return text;
        }
    }

    const char* translateFormat(const char* format) {
        if (!format) return format;
        const auto* translated = translate(format);
        // 保留参数类型、顺序、宽度和精度，译文中的占位符写错时使用原文。
        return translated == format || matchingFormatTokens(format, translated) ? translated : format;
    }

    void startup() {
        std::call_once(initialization, [] {
            loadBuiltin();
#ifndef REF_TRANSLATION_TEST
            try { loadExternal(); }
            catch (const std::exception& error) {
                spdlog::warn("[Translation] External dictionary: {}", error.what());
            }
            spdlog::info("[Translation] {} text + {} hash entries", dictionary.size(), hashDictionary.size());
#endif
            initialized = true;
        });
        g_imgui_translate_fn = &REF_ImGui_TranslateCB;
        g_imgui_translate_format_fn = &REF_ImGui_TranslateFormatCB;
    }
}
