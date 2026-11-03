#pragma once

namespace reframework::translation {
    void startup();
    const char* translate(const char* text, const char* textEnd = nullptr);
    const char* translateFormat(const char* format);
}

inline const char* REF_ImGui_TranslateCB(const char* text, const char* textEnd) {
    return reframework::translation::translate(text, textEnd);
}

inline const char* REF_ImGui_TranslateFormatCB(const char* format) {
    return reframework::translation::translateFormat(format);
}
