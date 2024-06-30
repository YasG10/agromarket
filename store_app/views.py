from decimal import Decimal
from django.forms import DecimalField
from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from sympy import Q
from .models import Order, Product
from .forms import OrderForm, ProductForm
from django.views.generic import ListView, UpdateView
from django.shortcuts import get_object_or_404
from django.views.generic import ListView, CreateView, DeleteView
from .models import Cart
from django.shortcuts import redirect
from django.views import View
from django.views.generic import ListView
from django.views.generic import DetailView, FormView
from django.urls import reverse, reverse_lazy
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from .models import Order, Product
from django.db.models import Sum
from django.db.models import Sum, F, FloatField
from django.utils.safestring import mark_safe
from .forms import CartForm
import json
from django.contrib import messages
from django.shortcuts import redirect
from .models import Cart, Order


class SellerRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_seller


class BuyerRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_buyer


class SalesReportView(LoginRequiredMixin, SellerRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        # Obtener el total de ventas del vendedor usando anotaciones con FloatField
        total_sales_float = (
            Order.objects.filter(product__seller=request.user, status="completed")
            .annotate(total_sale=F("quantity") * F("product__price"))
            .aggregate(total=Sum("total_sale", output_field=FloatField()))["total"]
            or 0.0
        )

        # Convertir el total de ventas a Decimal
        total_sales = Decimal(total_sales_float).quantize(Decimal("0.00"))

        # Obtener el conteo de ventas por producto
        product_sales = (
            Order.objects.filter(product__seller=request.user, status="completed")
            .values("product__name")
            .annotate(total_quantity=Sum("quantity"))
            .order_by("-total_quantity")
        )

        # Extraer datos para Chart.js
        products = [sale["product__name"] for sale in product_sales]
        quantities = [sale["total_quantity"] for sale in product_sales]

        context = {
            "total_sales": total_sales,
            "products": mark_safe(json.dumps(products)),
            "quantities": mark_safe(json.dumps(quantities)),
            "product_sales": product_sales,  # Asegúrate de pasar esto al contexto
        }
        return render(request, "store_app/sales_report.html", context)


class ProductListView(LoginRequiredMixin, SellerRequiredMixin, ListView):
    model = Product
    template_name = "store_app/product_list.html"

    def get_queryset(self):
        return Product.objects.filter(seller=self.request.user)


class ProductCreateView(LoginRequiredMixin, SellerRequiredMixin, CreateView):
    model = Product
    form_class = ProductForm
    template_name = "store_app/product_form.html"
    success_url = "/store/products/"

    def form_valid(self, form):
        form.instance.seller = self.request.user
        return super().form_valid(form)


class ProductUpdateView(LoginRequiredMixin, SellerRequiredMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = "store_app/product_form.html"
    success_url = "/store/products/"


class ProductDeleteView(LoginRequiredMixin, SellerRequiredMixin, DeleteView):
    model = Product
    template_name = "store_app/product_confirm_delete.html"
    success_url = "/store/products/"

    def get_queryset(self):
        return Product.objects.filter(seller=self.request.user)


class OrderCreateView(LoginRequiredMixin, BuyerRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        cart_items = Cart.objects.filter(buyer=request.user)
        total_cost = sum(
            Decimal(item.product.price) * Decimal(item.quantity) for item in cart_items
        )

        if request.user.balance < total_cost:
            messages.error(request, "Insufficient balance to complete the purchase.")
            return redirect("cart_list")

        for item in cart_items:
            product = item.product
            if item.quantity > product.quantity_available:
                messages.error(
                    request, f"Insufficient quantity available for {product.name}."
                )
                return redirect("cart_list")

        for item in cart_items:
            product = item.product
            product.quantity_available -= item.quantity
            product.save()

            Order.objects.create(
                buyer=request.user,
                product=product,
                quantity=item.quantity,
                shipping_address=request.user.address,
                status="pending",
            )
            item.delete()

        request.user.balance -= total_cost
        request.user.save()

        messages.success(request, "Order placed successfully.")
        return redirect("product_public_list")


class OrderDeleteView(LoginRequiredMixin, SellerRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        order_id = kwargs.get("pk")
        order = get_object_or_404(Order, pk=order_id)

        # Devolver la cantidad de productos al inventario del vendedor
        product = order.product
        product.quantity_available += order.quantity
        product.save()

        # Reembolsar el dinero al comprador
        order.buyer.balance += order.quantity * product.price
        order.buyer.save()

        order.delete()
        messages.success(request, "Order deleted successfully.")
        return redirect("order_list")


class OrderConfirmDeleteView(LoginRequiredMixin, SellerRequiredMixin, DeleteView):
    model = Order
    template_name = "store_app/order_confirm_delete.html"
    success_url = "/store/orders/"


class OrderListView(
    LoginRequiredMixin, SellerRequiredMixin, BuyerRequiredMixin, ListView
):
    model = Order
    template_name = "store_app/order_list.html"

    def get_queryset(self):
        return Order.objects.filter(product__seller=self.request.user)


from django.views.generic import UpdateView
from .forms import OrderForm


class OrderUpdateView(LoginRequiredMixin, SellerRequiredMixin, UpdateView):
    model = Order
    form_class = OrderForm
    template_name = "store_app/order_form.html"
    success_url = reverse_lazy('order_list')

    def form_valid(self, form):
        order = form.save(commit=False)
        original_status = Order.objects.get(pk=order.pk).status

        if original_status != "cancelled" and order.status == "cancelled":
            order.product.quantity_available += order.quantity
            order.product.save()

            order.buyer.balance += order.quantity * order.product.price
            order.buyer.save()

        if order.status == "completed":
            order.delete()
            return redirect(self.success_url)

        return super().form_valid(form)


class CartListView(LoginRequiredMixin, ListView):
    model = Cart
    template_name = "store_app/cart_list.html"

    def get_queryset(self):
        return Cart.objects.filter(buyer=self.request.user)


class CartAddView(LoginRequiredMixin, CreateView):
    model = Cart
    fields = ["product", "quantity"]
    template_name = "store_app/cart_form.html"
    success_url = "/store/cart/"

    def form_valid(self, form):
        form.instance.buyer = self.request.user
        return super().form_valid(form)


class CartDeleteView(LoginRequiredMixin, DeleteView):
    model = Cart
    template_name = "store_app/cart_confirm_delete.html"
    success_url = "/store/cart/"

    def get_queryset(self):
        return Cart.objects.filter(buyer=self.request.user)


class CheckoutView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        cart_items = Cart.objects.filter(buyer=request.user)
        total_cost = sum(item.product.price * item.quantity for item in cart_items)
        print(request)

        if request.user.balance < total_cost:
            return redirect("cart_list")

        for item in cart_items:
            Order.objects.create(
                buyer=request.user,
                product=item.product,
                quantity=item.quantity,
                shipping_address=request.address,
                status="pending",
            )
            item.product.quantity_available -= item.quantity
            item.product.save()
            item.delete()

        request.user.balance -= total_cost
        request.user.save()

        return redirect("order_list")


class ProductPublicListView(ListView):
    model = Product
    template_name = "store_app/product_public_list.html"
    context_object_name = "products"

    def get_queryset(self):
        queryset = Product.objects.all()
        query = self.request.GET.get("q")
        if query:
            queryset = queryset.filter(
                Q(name__icontains=query) | Q(description__icontains=query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["search_query"] = self.request.GET.get("q", "")
        return context


class ProductDetailView(DetailView, FormView):
    model = Product
    template_name = "store_app/product_detail.html"
    form_class = CartForm

    def get_success_url(self):
        return reverse("product_detail", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = CartForm(initial={"product": self.object})
        return context

    def form_valid(self, form):
        self.object = self.get_object()
        cart_item, created = Cart.objects.get_or_create(
            buyer=self.request.user,
            product=self.object,
            defaults={"quantity": form.cleaned_data["quantity"]},
        )
        if not created:
            cart_item.quantity += form.cleaned_data["quantity"]
            cart_item.save()
        return super().form_valid(form)
