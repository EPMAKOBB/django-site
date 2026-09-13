(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    var form = document.querySelector("form[data-lesson-defaults]");
    if (!form) return;
    var student = form.elements.teacher_student_link;
    var duration = form.elements.duration_minutes;
    var price = form.elements.price_amount;
    if (!student || !duration || !price) return;
    function applyDefaults(onlyEmpty) {
      var option = student.options[student.selectedIndex];
      if (!option || !option.dataset.duration) return;
      if (!onlyEmpty || !duration.value) duration.value = option.dataset.duration;
      if (!onlyEmpty || !price.value) price.value = option.dataset.price;
    }
    student.addEventListener("change", function () { applyDefaults(false); });
    applyDefaults(true);
  });
})();
